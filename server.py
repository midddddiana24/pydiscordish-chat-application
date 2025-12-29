import socket
import threading
import json
import time
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, simpledialog, filedialog
from tkinter.scrolledtext import ScrolledText
from datetime import datetime
import traceback

# ============================================================================
# CONFIGURATION
# ============================================================================
HOST = "0.0.0.0"
PORT = 55000
LOG_FILE = "server_chat_log.txt"
BANNED_FILE = "banned_users.txt"
USERS_DB = "users.json"
MAX_FILE_SIZE = 200 * 1024
ADMIN_PASSWORD = "admin123"  # CHANGE THIS IN PRODUCTION!

# Modern color scheme
MODERN_THEME = {
    'bg_primary': '#0f1419',
    'bg_secondary': '#1a1f2e',
    'bg_tertiary': '#0f1419',
    'accent': '#6366f1',
    'accent_hover': '#818cf8',
    'text_primary': '#f8fafc',
    'text_secondary': '#cbd5e1',
    'text_muted': '#64748b',
    'success': '#10b981',
    'danger': '#ef4444',
    'warning': '#f59e0b',
    'online': '#14b8a6',
}

# Global state
clients_lock = threading.Lock()
clients = {}  # username -> {conn, addr, muted_until, is_admin, room}
banned = set()
rooms = {}  # room_name -> set of usernames
user_rooms = {}  # username -> room_name
room_passwords = {}  # room_name -> password

DEFAULT_FONT = "Segoe UI"
FALLBACK_FONT = "Arial"


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================
def safe_font(family, size=10, weight="normal"):
    """Create font with fallback"""
    try:
        return tkfont.Font(family=family, size=size, weight=weight)
    except:
        return tkfont.Font(family=FALLBACK_FONT, size=size, weight=weight)


def now_ts():
    """Get current timestamp"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_banned():
    """Load banned users from file"""
    global banned
    if os.path.exists(BANNED_FILE):
        try:
            with open(BANNED_FILE, "r", encoding="utf-8") as f:
                banned = set(x.strip() for x in f if x.strip())
        except:
            banned = set()


def save_banned():
    """Save banned users to file"""
    try:
        with open(BANNED_FILE, "w", encoding="utf-8") as f:
            for u in sorted(banned):
                f.write(u + "\n")
    except Exception as e:
        print(f"Failed to save banned list: {e}")


def load_users():
    """Load user database"""
    if not os.path.exists(USERS_DB):
        with open(USERS_DB, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return {}

    try:
        with open(USERS_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_users(users):
    """Save user database"""
    try:
        with open(USERS_DB, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        print(f"Failed to save users: {e}")


def register_user(username, password):
    """Register new user"""
    users = load_users()
    if username in users:
        return False
    users[username] = password
    save_users(users)
    return True


def authenticate_user(username, password):
    """Authenticate user"""
    users = load_users()
    return users.get(username) == password


def send_json(conn, obj):
    """Send JSON object to connection"""
    try:
        data = json.dumps(obj, ensure_ascii=False) + "\n"
        conn.sendall(data.encode("utf-8"))
        return True
    except:
        return False


def broadcast(obj, exclude=None, room=None):
    """Broadcast message to all clients (optionally filtered)"""
    with clients_lock:
        for uname, info in list(clients.items()):
            if exclude and uname in exclude:
                continue
            if room and user_rooms.get(uname) != room:
                continue
            try:
                send_json(info['conn'], obj)
            except:
                pass


def save_log(line):
    """Append line to log file"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"Failed to write log: {e}")


# ============================================================================
# CLIENT MANAGEMENT
# ============================================================================
def send_userlist(gui_app=None):
    """Send updated user list to all clients"""
    with clients_lock:
        msg = {
            "type": "userlist",
            "users": list(clients.keys()),
            "rooms": {room: list(members) for room, members in rooms.items()},
            "user_rooms": dict(user_rooms)
        }
        for uname, info in list(clients.items()):
            try:
                send_json(info['conn'], msg)
            except:
                pass


def remove_client(username, gui_app=None):
    """Remove client from server"""
    with clients_lock:
        info = clients.pop(username, None)

        # Remove from room
        room = user_rooms.pop(username, None)
        if room and username in rooms.get(room, set()):
            rooms[room].discard(username)
            if not rooms[room]:
                del rooms[room]

    if info:
        try:
            info['conn'].close()
        except:
            pass

        msg = f"{username} left the chat."
        broadcast({"type": "system", "message": msg})
        save_log(f"[{now_ts()}] LEAVE: {msg}")

        if gui_app:
            gui_app.log(msg, "leave")
            gui_app.update_lists()


def handle_join(conn, addr, username, gui_app=None):
    """Handle client join"""
    username = username.strip()

    if not username:
        send_json(conn, {"type": "system", "message": "Empty username rejected."})
        conn.close()
        return False

    if username in banned:
        send_json(conn, {"type": "system", "message": "You are banned from this server."})
        conn.close()
        return False

    with clients_lock:
        if username in clients:
            send_json(conn, {"type": "system", "message": "Username already in use."})
            conn.close()
            return False

        clients[username] = {
            "conn": conn,
            "addr": addr,
            "muted_until": 0,
            "is_admin": False,
            "joined": time.time()
        }

    msg = f"{username} joined the chat."
    broadcast({"type": "system", "message": msg})
    send_userlist(gui_app)
    save_log(f"[{now_ts()}] JOIN: {username} from {addr[0]}:{addr[1]}")

    if gui_app:
        gui_app.log(msg, "join")
        gui_app.update_lists()

    return True


# ============================================================================
# COMMAND HANDLER
# ============================================================================
def handle_command(sender, cmd, gui_app=None):
    """Handle chat commands"""
    parts = cmd.split(maxsplit=1) if cmd else []
    if not parts:
        return

    cmd0 = parts[0].lower()

    with clients_lock:
        sender_info = clients.get(sender)

    if not sender_info:
        return

    def admin_required():
        if not sender_info.get("is_admin"):
            send_json(sender_info['conn'], {"type": "system", "message": "⚠️ Admin rights required."})
            return False
        return True

    ts = now_ts()

    try:
        # Admin authentication
        if cmd0 == "/admin":
            cmd_parts = cmd.split()
            if len(cmd_parts) >= 2 and cmd_parts[1] == ADMIN_PASSWORD:
                sender_info["is_admin"] = True
                msg = f"👑 {sender} is now an admin."
                broadcast({"type": "system", "message": msg})
                save_log(f"[{ts}] ADMIN: {msg}")
                if gui_app:
                    gui_app.log(msg, "admin")
                    gui_app.update_lists()
            else:
                send_json(sender_info['conn'], {"type": "system", "message": "❌ Invalid admin password."})

        # List users
        elif cmd0 == "/list" or cmd0 == "/users":
            user_list = ", ".join(sorted(clients.keys())) if clients else "(none)"
            send_json(sender_info['conn'], {"type": "system", "message": f"👥 Online Users: {user_list}"})
            if gui_app:
                gui_app.log(f"{sender} requested user list", "system")

        # Show own username
        elif cmd0 == "/whoami":
            send_json(sender_info['conn'], {"type": "system", "message": f"You are: {sender}"})

        # Create room
        elif cmd0 == "/create":
            cmd_parts = cmd.split(maxsplit=2)
            if len(cmd_parts) < 2:
                send_json(sender_info['conn'], {"type": "system", "message": "Usage: /create room_name [password]"})
                return

            room_name = cmd_parts[1]
            pwd = cmd_parts[2] if len(cmd_parts) > 2 else ""

            if room_name in rooms:
                send_json(sender_info['conn'], {"type": "system", "message": f"❌ Room '{room_name}' already exists."})
                return

            rooms[room_name] = set([sender])
            user_rooms[sender] = room_name
            if pwd:
                room_passwords[room_name] = pwd

            msg = f"✅ Created room '{room_name}'"
            if pwd:
                msg += " (password protected)"
            send_json(sender_info['conn'], {"type": "system", "message": msg})
            broadcast({"type": "system", "message": f"📢 {sender} created room '{room_name}'"})
            save_log(f"[{ts}] ROOM: {sender} created '{room_name}'")
            if gui_app:
                gui_app.log(f"{sender} created room '{room_name}'", "system")
            send_userlist(gui_app)

        # Join room
        elif cmd0 == "/join":
            cmd_parts = cmd.split(maxsplit=2)
            if len(cmd_parts) < 2:
                send_json(sender_info['conn'], {"type": "system", "message": "Usage: /join room_name [password]"})
                return

            room_name = cmd_parts[1]
            pwd = cmd_parts[2] if len(cmd_parts) > 2 else ""

            # Check password
            if room_name in room_passwords:
                if room_passwords[room_name] != pwd:
                    send_json(sender_info['conn'], {"type": "system", "message": "❌ Incorrect room password."})
                    return
            elif pwd and room_name not in rooms:
                # New room with password
                room_passwords[room_name] = pwd

            # Remove from previous room
            prev_room = user_rooms.get(sender)
            if prev_room and sender in rooms.get(prev_room, set()):
                rooms[prev_room].discard(sender)
                if not rooms[prev_room]:
                    del rooms[prev_room]
                broadcast({"type": "system", "message": f"📢 {sender} left room '{prev_room}'"})

            # Add to new room
            rooms.setdefault(room_name, set()).add(sender)
            user_rooms[sender] = room_name

            send_json(sender_info['conn'], {"type": "system", "message": f"✅ You joined room '{room_name}'."})
            broadcast({"type": "system", "message": f"📢 {sender} joined room '{room_name}'."}, room=room_name)
            save_log(f"[{ts}] ROOM: {sender} joined '{room_name}'")
            if gui_app:
                gui_app.log(f"{sender} joined room '{room_name}'", "system")
            send_userlist(gui_app)

        # Leave room
        elif cmd0 == "/leave":
            current_room = user_rooms.get(sender)
            if not current_room:
                send_json(sender_info['conn'], {"type": "system", "message": "You are not in any room."})
                return

            rooms[current_room].discard(sender)
            if not rooms[current_room]:
                del rooms[current_room]
            del user_rooms[sender]

            send_json(sender_info['conn'], {"type": "system", "message": f"✅ You left room '{current_room}'."})
            broadcast({"type": "system", "message": f"📢 {sender} left room '{current_room}'."})
            save_log(f"[{ts}] ROOM: {sender} left '{current_room}'")
            if gui_app:
                gui_app.log(f"{sender} left room '{current_room}'", "system")
            send_userlist(gui_app)

        # List rooms
        elif cmd0 == "/rooms":
            room_list = ", ".join(sorted(rooms.keys())) if rooms else "(none)"
            send_json(sender_info['conn'], {"type": "system", "message": f"💬 Available rooms: {room_list}"})

        # Action message (/me)
        elif cmd0 == "/me":
            if len(parts) < 2:
                send_json(sender_info['conn'], {"type": "system", "message": "Usage: /me <action>"})
                return

            action = parts[1]
            current_room = user_rooms.get(sender)
            broadcast({
                "type": "broadcast",
                "from": sender,
                "message": f"✨ {sender} {action}",
                "timestamp": ts
            }, exclude=[sender], room=current_room)
            save_log(f"[{ts}] ACTION: {sender} {action}")
            if gui_app:
                gui_app.log(f"*{sender} {action}", "message")

        # Mute user
        elif cmd0 == "/mute" and admin_required():
            cmd_parts = cmd.split()
            if len(cmd_parts) < 3:
                send_json(sender_info['conn'], {"type": "system", "message": "Usage: /mute username seconds"})
                return

            target, seconds_str = cmd_parts[1], cmd_parts[2]
            try:
                seconds = int(seconds_str)
            except ValueError:
                send_json(sender_info['conn'], {"type": "system", "message": "❌ Invalid seconds value"})
                return

            with clients_lock:
                target_info = clients.get(target)

            if target_info:
                target_info["muted_until"] = time.time() + seconds
                send_json(target_info["conn"], {"type": "system", "message": f"🔇 You are muted for {seconds} seconds."})
                msg = f"🔇 {target} was muted by {sender} for {seconds}s."
                broadcast({"type": "system", "message": msg})
                save_log(f"[{ts}] MUTE: {msg}")
                if gui_app:
                    gui_app.log(msg, "admin")
            else:
                send_json(sender_info["conn"], {"type": "system", "message": f"❌ User '{target}' not found."})

        # Unmute user
        elif cmd0 == "/unmute" and admin_required():
            cmd_parts = cmd.split()
            if len(cmd_parts) < 2:
                send_json(sender_info['conn'], {"type": "system", "message": "Usage: /unmute username"})
                return

            target = cmd_parts[1]
            with clients_lock:
                target_info = clients.get(target)

            if target_info:
                target_info["muted_until"] = 0
                send_json(target_info["conn"], {"type": "system", "message": "🔊 You are no longer muted."})
                msg = f"🔊 {target} was unmuted by {sender}."
                broadcast({"type": "system", "message": msg})
                save_log(f"[{ts}] UNMUTE: {msg}")
                if gui_app:
                    gui_app.log(msg, "admin")
            else:
                send_json(sender_info["conn"], {"type": "system", "message": f"❌ User '{target}' not found."})

        # Kick user
        elif cmd0 == "/kick" and admin_required():
            cmd_parts = cmd.split()
            if len(cmd_parts) < 2:
                send_json(sender_info["conn"], {"type": "system", "message": "Usage: /kick username"})
                return

            target = cmd_parts[1]
            with clients_lock:
                target_info = clients.get(target)

            if target_info:
                send_json(target_info["conn"], {"type": "system", "message": "⚠️ You were kicked by an admin."})
                remove_client(target, gui_app)
                msg = f"👢 {target} was kicked by {sender}."
                broadcast({"type": "system", "message": msg})
                save_log(f"[{ts}] KICK: {msg}")
                if gui_app:
                    gui_app.log(msg, "admin")
            else:
                send_json(sender_info["conn"], {"type": "system", "message": f"❌ User '{target}' not found."})

        # Ban user
        elif cmd0 == "/ban" and admin_required():
            cmd_parts = cmd.split()
            if len(cmd_parts) < 2:
                send_json(sender_info["conn"], {"type": "system", "message": "Usage: /ban username"})
                return

            target = cmd_parts[1]
            banned.add(target)
            save_banned()
            msg = f"🚫 {target} was banned by {sender}."
            broadcast({"type": "system", "message": msg})
            save_log(f"[{ts}] BAN: {msg}")
            if gui_app:
                gui_app.log(msg, "admin")
                gui_app.update_lists()
            remove_client(target, gui_app)

        # Unban user
        elif cmd0 == "/unban" and admin_required():
            cmd_parts = cmd.split()
            if len(cmd_parts) < 2:
                send_json(sender_info["conn"], {"type": "system", "message": "Usage: /unban username"})
                return

            target = cmd_parts[1]
            if target in banned:
                banned.remove(target)
                save_banned()
                msg = f"✅ {target} was unbanned by {sender}."
                broadcast({"type": "system", "message": msg})
                save_log(f"[{ts}] UNBAN: {msg}")
                if gui_app:
                    gui_app.log(msg, "admin")
                    gui_app.update_lists()
            else:
                send_json(sender_info["conn"], {"type": "system", "message": f"❌ User '{target}' is not banned."})

        # List banned users
        elif cmd0 == "/listbans" and admin_required():
            bans_str = f"Banned users: {', '.join(sorted(banned)) or '(none)'}"
            send_json(sender_info["conn"], {"type": "system", "message": bans_str})
            if gui_app:
                gui_app.log(f"{sender} requested ban list", "admin")

        # Announce message (admin only)
        elif cmd0 == "/announce" and admin_required():
            if len(parts) < 2:
                send_json(sender_info['conn'], {"type": "system", "message": "Usage: /announce <message>"})
                return

            announcement = parts[1]
            msg = f"📢 [ANNOUNCEMENT] {announcement}"
            broadcast({"type": "system", "message": msg})
            save_log(f"[{ts}] ANNOUNCE: {msg}")
            if gui_app:
                gui_app.log(msg, "admin")

        # Help
        elif cmd0 == "/help" or cmd0 == "/?":
            help_text = (
                "📚 AVAILABLE COMMANDS\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🎯 BASIC COMMANDS:\n"
                "/help or /? - Show this help\n"
                "/list or /users - Show online users\n"
                "/whoami - Show your username\n"
                "/me <action> - Send action message\n\n"
                "💬 ROOM COMMANDS:\n"
                "/create <room> [pwd] - Create room\n"
                "/join <room> [pwd] - Join room\n"
                "/leave - Leave current room\n"
                "/rooms - List all rooms\n\n"
                "/admin <password> - Become admin"
            )
            if sender_info.get("is_admin"):
                help_text += (
                    "\n\n👑 ADMIN COMMANDS:\n"
                    "/kick <user> - Kick user\n"
                    "/ban <user> - Ban user\n"
                    "/unban <user> - Unban user\n"
                    "/mute <user> <sec> - Mute user\n"
                    "/unmute <user> - Unmute user\n"
                    "/listbans - List banned users\n"
                    "/announce <msg> - Send announcement"
                )
            send_json(sender_info['conn'], {"type": "system", "message": help_text})

        else:
            send_json(sender_info["conn"], {"type": "system", "message": "❌ Unknown command. Use /help for help."})

    except Exception as e:
        # Catch any errors in command processing
        send_json(sender_info["conn"], {"type": "system", "message": f"❌ Command error: {str(e)}"})
        if gui_app:
            gui_app.log(f"Command error from {sender}: {str(e)}", "error")


# ============================================================================
# CLIENT HANDLER
# ============================================================================
def handle_client(conn, addr, gui_app=None):
    """Handle individual client connection"""
    username = None
    buffer = ""

    try:
        # Set initial timeout for authentication
        conn.settimeout(30)

        # Read first message (authentication)
        while True:
            chunk = conn.recv(4096).decode('utf-8')
            if not chunk:
                return

            buffer += chunk
            if '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                break

        try:
            obj = json.loads(line.strip())
        except json.JSONDecodeError:
            send_json(conn, {"type": "system", "message": "❌ Invalid message format."})
            conn.close()
            return

        if obj.get("type") != "auth":
            send_json(conn, {"type": "system", "message": "❌ Expected authentication message."})
            conn.close()
            return

        username = obj.get("username", "").strip()
        password = obj.get("password", "").strip()
        is_register = obj.get("register", False)

        # Validate inputs
        if not username:
            send_json(conn, {"type": "system", "message": "❌ Username cannot be empty."})
            conn.close()
            return

        if len(username) < 3:
            send_json(conn, {"type": "system", "message": "❌ Username must be at least 3 characters."})
            conn.close()
            return

        if not password:
            send_json(conn, {"type": "system", "message": "❌ Password cannot be empty."})
            conn.close()
            return

        if len(password) < 4:
            send_json(conn, {"type": "system", "message": "❌ Password must be at least 4 characters."})
            conn.close()
            return

        # Handle registration
        if is_register:
            if register_user(username, password):
                send_json(conn, {
                    "type": "system",
                    "message": f"✅ Account '{username}' created successfully! Please login."
                })
                if gui_app:
                    gui_app.log(f"New user registered: {username}", "system")
            else:
                send_json(conn, {
                    "type": "system",
                    "message": f"❌ Username '{username}' already exists. Please choose another."
                })
            conn.close()
            return

        # Authenticate existing user
        if not authenticate_user(username, password):
            send_json(conn, {
                "type": "system",
                "message": "❌ Invalid username or password. Please try again."
            })
            if gui_app:
                gui_app.log(f"Failed login attempt for: {username} from {addr[0]}", "error")
            conn.close()
            return

        # Send auth success response
        send_json(conn, {
            "type": "system",
            "message": "✅ Authentication successful!"
        })

        # Remove timeout after successful auth
        conn.settimeout(None)

        # Join server
        if not handle_join(conn, addr, username, gui_app):
            return

        # Send welcome message
        send_json(conn, {
            "type": "system",
            "message": f"🎉 Welcome to PyDiscordish, {username}! Type /help for commands."
        })

        # Reset buffer for main loop
        buffer = ""

        # Configure socket for stability
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        conn.settimeout(None)  # Blocking mode (no timeout)

        # Main message loop
        while True:
            try:
                chunk = conn.recv(4096)

                if not chunk:
                    # Connection closed by client
                    if gui_app:
                        gui_app.log(f"Connection closed by {username}", "system")
                    break

                buffer += chunk.decode('utf-8', errors='replace')
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
                if gui_app:
                    gui_app.log(f"Connection lost with {username}: {type(e).__name__}", "error")
                break
            except Exception as e:
                if gui_app:
                    gui_app.log(f"Error with {username}: {type(e).__name__}", "error")
                break
            # Process complete lines (JSON messages)
            lines_to_process = buffer.split('\n')
            buffer = lines_to_process[-1]  # Keep incomplete line in buffer

            for line in lines_to_process[:-1]:
                if not line.strip():
                    continue

                try:
                    data = json.loads(line.strip())
                except json.JSONDecodeError:
                    # Invalid JSON, skip this line
                    continue
                except Exception as e:
                    if gui_app:
                        gui_app.log(f"JSON parse error from {username}: {e}", "error")
                    continue

                # Get client info
                with clients_lock:
                    info = clients.get(username)

                if not info:
                    # Client was removed (kicked/banned)
                    break

                # Auto-unmute
                if info["muted_until"] < time.time():
                    info["muted_until"] = 0

                # Check if muted
                if info["muted_until"] > time.time() and data.get("type") in ("broadcast", "private"):
                    send_json(conn, {"type": "system", "message": "🔇 You are muted."})
                    continue

                # Handle message types
                mtype = data.get("type")
                ts = now_ts()

                try:
                    if mtype == "broadcast":
                        msg = data.get("message", "")
                        room = user_rooms.get(username)
                        broadcast({
                            "type": "broadcast",
                            "from": username,
                            "message": msg,
                            "timestamp": ts
                        }, exclude=[username], room=room)
                        save_log(f"[{ts}] {username} (room:{room}): {msg}")
                        if gui_app:
                            gui_app.log(f"{username}: {msg}", "message")

                    elif mtype == "private":
                        to = data.get("to")
                        msg = data.get("message", "")
                        with clients_lock:
                            recipient = clients.get(to)

                        if recipient:
                            pm = {
                                "type": "private",
                                "from": username,
                                "message": msg,
                                "timestamp": ts
                            }
                            send_json(recipient["conn"], pm)
                            send_json(conn, pm)
                            save_log(f"[{ts}] {username} -> {to}: {msg}")
                            if gui_app:
                                gui_app.log(f"{username} -> {to}: {msg}", "private")
                        else:
                            send_json(conn, {"type": "system", "message": f"❌ User '{to}' not found."})

                    elif mtype == "command":
                        handle_command(username, data.get("command", ""), gui_app)

                    elif mtype == "typing":
                        status = data.get("status", False)
                        broadcast({
                            "type": "typing",
                            "user": username,
                            "status": status
                        }, exclude=[username])

                    elif mtype == "file":
                        filename = data.get("filename", "unknown")
                        size = data.get("size", 0)
                        to_target = data.get("to", "All")

                        save_log(f"[{ts}] FILE: {username} sent {filename} ({size}B) to {to_target}")
                        if gui_app:
                            gui_app.log(f"{username} sent file: {filename}", "file")

                        if to_target == "All":
                            room = user_rooms.get(username)
                            broadcast(data, exclude=[username], room=room)
                        else:
                            with clients_lock:
                                recipient = clients.get(to_target)
                            if recipient:
                                send_json(recipient["conn"], data)

                except Exception as e:
                    if gui_app:
                        gui_app.log(f"Error processing message from {username}: {e}", "error")

    except socket.timeout:
        pass  # Timeout during auth is handled
    except ConnectionResetError:
        pass  # Expected on disconnect
    except ConnectionAbortedError:
        pass  # Expected on disconnect
    except BrokenPipeError:
        pass  # Expected on disconnect
    except OSError:
        pass  # OS-level socket error
    except Exception as e:
        traceback.print_exc()

    finally:
        if username:
            remove_client(username, gui_app)


# ============================================================================
# SERVER LOOP
# ============================================================================
def server_loop(gui_app):
    """Main server loop"""
    load_banned()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        srv.bind((HOST, PORT))
        srv.listen(100)

        gui_app.log(f"✅ Server started on {HOST}:{PORT}", "system")
        gui_app.update_status(f"🚀 Running on {HOST}:{PORT}")

        while gui_app.running:
            try:
                srv.settimeout(1.0)
                conn, addr = srv.accept()
                threading.Thread(
                    target=handle_client,
                    args=(conn, addr, gui_app),
                    daemon=True
                ).start()
                gui_app.bell()
            except socket.timeout:
                continue
            except Exception as e:
                if gui_app.running:
                    gui_app.log(f"Accept error: {e}", "error")

    except Exception as e:
        gui_app.log(f"Server error: {e}", "error")

    finally:
        srv.close()
        gui_app.log("🛑 Server stopped.", "system")


# ============================================================================
# MODERN SERVER GUI
# ============================================================================
class ModernButton(tk.Button):
    """Styled button with smooth hover effects"""

    def __init__(self, parent, text="", command=None, style="primary", theme=MODERN_THEME, **kwargs):
        self.style = style
        self.theme = theme
        colors = self._get_colors()

        super().__init__(
            parent,
            text=text,
            command=command,
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=8,
            font=safe_font(DEFAULT_FONT, 10, "bold"),
            cursor="hand2",
            bg=colors['bg'],
            fg=colors['fg'],
            activebackground=colors['hover'],
            activeforeground=colors['fg'],
            **kwargs
        )

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _get_colors(self):
        if self.style == "primary":
            return {'bg': self.theme['accent'], 'fg': self.theme['text_primary'], 'hover': self.theme['accent_hover']}
        elif self.style == "danger":
            return {'bg': self.theme['danger'], 'fg': self.theme['text_primary'], 'hover': '#ef5350'}
        elif self.style == "success":
            return {'bg': self.theme['success'], 'fg': self.theme['text_primary'], 'hover': '#34d399'}
        elif self.style == "secondary":
            return {'bg': self.theme['bg_secondary'], 'fg': self.theme['text_primary'], 'hover': self.theme['bg_tertiary']}
        return {'bg': self.theme['bg_secondary'], 'fg': self.theme['text_primary'], 'hover': self.theme['bg_tertiary']}

    def _on_enter(self, e):
        colors = self._get_colors()
        self.configure(bg=colors['hover'])

    def _on_leave(self, e):
        colors = self._get_colors()
        self.configure(bg=colors['bg'])


class ServerGUI(tk.Tk):
    """Modern server admin interface"""

    def __init__(self):
        super().__init__()

        self.title("PyDiscordish Server Admin Panel")
        self.geometry("1100x700")
        self.minsize(900, 500)

        self.running = True
        self.theme = MODERN_THEME

        # Fonts
        self.font_title = safe_font(DEFAULT_FONT, 16, "bold")
        self.font_header = safe_font(DEFAULT_FONT, 12, "bold")
        self.font_body = safe_font(DEFAULT_FONT, 10)
        self.font_small = safe_font(DEFAULT_FONT, 9)

        # Auth check
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        if not self.authenticate_admin():
            return

        self._build_ui()

        # Start server
        threading.Thread(target=server_loop, args=(self,), daemon=True).start()

        # Periodic updates
        self.after(1000, self.periodic_update)

    def authenticate_admin(self):
        """Admin password check"""
        password = simpledialog.askstring(
            "Admin Authentication",
            f"Enter admin password:\n(Default: {ADMIN_PASSWORD})",
            show="•",
            parent=self
        )

        if password != ADMIN_PASSWORD:
            messagebox.showerror("Access Denied", "Invalid admin password!")
            self.destroy()
            return False
        return True

    def server_refresh(self):
        """Refresh server - update all lists and UI"""
        self.update_lists()
        self.log("🔄 Server refreshed - all lists updated", "system")

    def show_help_dialog(self):
        """Show help dialog with all admin commands"""
        help_window = tk.Toplevel(self)
        help_window.title("Admin Commands Help")
        help_window.geometry("700x750")
        help_window.configure(bg=self.theme['bg_primary'])
        help_window.resizable(True, True)

        # Header
        header_frame = tk.Frame(help_window, bg=self.theme['bg_secondary'], height=70)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        title_frame = tk.Frame(header_frame, bg=self.theme['bg_secondary'])
        title_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        tk.Label(
            title_frame,
            text="📚",
            font=safe_font(DEFAULT_FONT, 24),
            bg=self.theme['bg_secondary'],
            fg=self.theme['accent']
        ).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(
            title_frame,
            text="Admin Command Reference",
            font=safe_font(DEFAULT_FONT, 14, "bold"),
            bg=self.theme['bg_secondary'],
            fg=self.theme['text_primary']
        ).pack(side=tk.LEFT)

        # Scrollable content
        help_text = ScrolledText(
            help_window,
            wrap=tk.WORD,
            font=self.font_body,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_primary'],
            bd=0,
            relief=tk.FLAT,
            padx=15,
            pady=15
        )
        help_text.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

        commands_info = """🎯 USER MANAGEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/kick <user>
  → Remove user from server immediately

/ban <user>
  → Permanently ban user from server

/unban <user>
  → Unban a previously banned user

/listbans
  → Show all banned users

/mute <user> <seconds>
  → Mute user for specified seconds

💬 ROOM MANAGEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(Right-click on rooms in sidebar)
  → Set/Remove password
  → Kick all users from room
  → Delete room

📢 SERVER CONTROL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/broadcast <message>
  → Send message to all users

/stats
  → Show server statistics

/serverinfo
  → Show detailed server information

/clearlog
  → Clear server log display

📋 INFORMATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/help
  → Show this help message

SIDEBAR ACTIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 Online Users  → Right-click for options:
                   • Kick user
                   • Ban user
                   • Mute (30s or 5min)
                   • Send message

💬 Rooms        → Right-click for options:
                   • Set/Remove password
                   • Kick all users
                   • Delete room

🚫 Banned Users → Right-click to unban

🔄 Refresh      → Update all lists

💾 Save Log     → Export logs to file"""

        help_text.insert("1.0", commands_info)
        help_text.configure(state=tk.DISABLED)

        # Footer with close button
        footer_frame = tk.Frame(help_window, bg=self.theme['bg_secondary'], height=60)
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM)
        footer_frame.pack_propagate(False)

        btn_frame = tk.Frame(footer_frame, bg=self.theme['bg_secondary'])
        btn_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=12)

        ModernButton(
            btn_frame,
            text="✓ Close Help",
            command=help_window.destroy,
            style="primary",
            theme=self.theme
        ).pack(side=tk.RIGHT)

    def _build_ui(self):
        """Build the admin interface"""
        self.configure(bg=self.theme['bg_primary'])

        # Top bar
        self._create_top_bar()

        # Main container
        main = tk.Frame(self, bg=self.theme['bg_primary'])
        main.pack(expand=True, fill=tk.BOTH)

        # Sidebar
        self._create_sidebar(main)

        # Log area
        self._create_log_area(main)

        # Command bar
        self._create_command_bar()

    def _create_top_bar(self):
        """Create top navigation"""
        top = tk.Frame(self, bg=self.theme['bg_primary'], height=70)
        top.pack(side=tk.TOP, fill=tk.X)
        top.pack_propagate(False)

        # Title
        title_frame = tk.Frame(top, bg=self.theme['bg_primary'])
        title_frame.pack(side=tk.LEFT, padx=20, pady=15)

        tk.Label(
            title_frame,
            text="🛡️",
            font=safe_font(DEFAULT_FONT, 28),
            bg=self.theme['bg_primary'],
            fg=self.theme['accent']
        ).pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(
            title_frame,
            text="Server Admin Panel",
            font=self.font_title,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_primary']
        ).pack(side=tk.LEFT)

        # Developer credit
        dev_label = tk.Label(
            top,
            text="Developer: GODDDOG",
            font=self.font_small,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_muted']
        )
        dev_label.pack(side=tk.LEFT, padx=20)

        # Status and stats
        info_frame = tk.Frame(top, bg=self.theme['bg_primary'])
        info_frame.pack(side=tk.RIGHT, padx=20, pady=15)

        # Refresh button
        ModernButton(
            info_frame,
            text="🔄",
            command=self.server_refresh,
            style="secondary",
            theme=self.theme
        ).pack(side=tk.RIGHT, padx=5)

        # Help button (styled modernly)
        help_btn = ModernButton(
            info_frame,
            text="? Help",
            command=self.show_help_dialog,
            style="primary",
            theme=self.theme
        )
        help_btn.pack(side=tk.RIGHT, padx=(0, 10))

        self.status_var = tk.StringVar(value="🟡 Initializing...")
        tk.Label(
            info_frame,
            textvariable=self.status_var,
            font=self.font_small,
            bg=self.theme['bg_primary'],
            fg=self.theme['online']
        ).pack(side=tk.RIGHT, padx=(10, 0))

        self.stats_var = tk.StringVar(value="Users: 0 | Rooms: 0 | Banned: 0")
        tk.Label(
            info_frame,
            textvariable=self.stats_var,
            font=self.font_small,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_muted']
        ).pack(side=tk.RIGHT)

    def _create_sidebar(self, parent):
        """Create sidebar with lists"""
        sidebar = tk.Frame(parent, width=300, bg=self.theme['bg_secondary'])
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Online users
        self._create_list_section(sidebar, "🟢 Online Users", "users")

        # Rooms
        self._create_list_section(sidebar, "💬 Rooms", "rooms")

        # Banned users
        self._create_list_section(sidebar, "🚫 Banned Users", "banned")

        # Action buttons
        btn_frame = tk.Frame(sidebar, bg=self.theme['bg_secondary'])
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=12)

        ModernButton(
            btn_frame,
            text="🔄 Refresh",
            command=self.update_lists,
            style="secondary",
            theme=self.theme
        ).pack(fill=tk.X, pady=4)

        ModernButton(
            btn_frame,
            text="💾 Save Log",
            command=self.save_log_file,
            style="secondary",
            theme=self.theme
        ).pack(fill=tk.X, pady=4)

    def _create_list_section(self, parent, title, list_type):
        """Create a list section"""
        container = tk.Frame(parent, bg=self.theme['bg_secondary'])
        container.pack(fill=tk.BOTH, expand=True, padx=12, pady=(12, 0))

        # Header
        tk.Label(
            container,
            text=title,
            font=self.font_body,
            bg=self.theme['bg_secondary'],
            fg=self.theme['accent'],
            anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))

        # Listbox
        listbox = tk.Listbox(
            container,
            font=self.font_body,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_primary'],
            selectbackground=self.theme['accent'],
            selectforeground=self.theme['text_primary'],
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
            cursor="hand2"
        )
        listbox.pack(fill=tk.BOTH, expand=True)

        # Store reference
        if list_type == "users":
            self.users_listbox = listbox
            listbox.bind("<Button-3>", self.on_user_right_click)
        elif list_type == "rooms":
            self.rooms_listbox = listbox
            listbox.bind("<Button-3>", self.on_room_right_click)
        elif list_type == "banned":
            self.banned_listbox = listbox
            listbox.bind("<Button-3>", self.on_banned_right_click)

    def _create_log_area(self, parent):
        """Create log display area"""
        log_frame = tk.Frame(parent, bg=self.theme['bg_primary'])
        log_frame.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH)

        # Header
        header = tk.Frame(log_frame, bg=self.theme['bg_primary'], height=50)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header,
            text="📋 Server Logs",
            font=self.font_header,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_primary'],
            anchor="w"
        ).pack(side=tk.LEFT, padx=20, pady=12)

        # Log display
        self.log_display = ScrolledText(
            log_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=self.font_body,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_primary'],
            insertbackground=self.theme['accent'],
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
            padx=15,
            pady=10
        )
        self.log_display.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

        # Configure tags
        self.log_display.tag_configure("system", foreground=self.theme['success'])
        self.log_display.tag_configure("join", foreground=self.theme['online'])
        self.log_display.tag_configure("leave", foreground=self.theme['danger'])
        self.log_display.tag_configure("message", foreground=self.theme['text_primary'])
        self.log_display.tag_configure("private", foreground=self.theme['accent'])
        self.log_display.tag_configure("admin", foreground=self.theme['warning'])
        self.log_display.tag_configure("file", foreground=self.theme['success'])
        self.log_display.tag_configure("error", foreground=self.theme['danger'])
        self.log_display.tag_configure("timestamp", foreground=self.theme['text_muted'], font=self.font_small)

    def _create_command_bar(self):
        """Create command input bar"""
        cmd_frame = tk.Frame(self, bg=self.theme['bg_secondary'], height=65)
        cmd_frame.pack(side=tk.BOTTOM, fill=tk.X)
        cmd_frame.pack_propagate(False)

        tk.Label(
            cmd_frame,
            text="📝 Admin Command:",
            font=self.font_body,
            bg=self.theme['bg_secondary'],
            fg=self.theme['text_muted']
        ).pack(side=tk.LEFT, padx=15, pady=12)

        self.cmd_var = tk.StringVar()
        cmd_entry = tk.Entry(
            cmd_frame,
            textvariable=self.cmd_var,
            font=self.font_body,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_primary'],
            insertbackground=self.theme['accent'],
            bd=0,
            relief=tk.FLAT
        )
        cmd_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10), pady=10, ipady=8)
        cmd_entry.bind("<Return>", self.execute_command)

        ModernButton(
            cmd_frame,
            text="⚡ Execute",
            command=self.execute_command,
            style="primary",
            theme=self.theme
        ).pack(side=tk.RIGHT, padx=15, pady=10)

    # ========================================================================
    # LOG FUNCTIONS
    # ========================================================================

    def log(self, message, tag="system"):
        """Add message to log display"""
        self.log_display.configure(state=tk.NORMAL)
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_display.insert(tk.END, f"[{ts}] ", "timestamp")
        self.log_display.insert(tk.END, f"{message}\n", tag)
        self.log_display.configure(state=tk.DISABLED)
        self.log_display.see(tk.END)

    # ========================================================================
    # UI UPDATE FUNCTIONS
    # ========================================================================

    def update_lists(self):
        """Update all listboxes"""
        # Online users
        self.users_listbox.delete(0, tk.END)
        with clients_lock:
            for username, info in sorted(clients.items()):
                display = f"👑 {username}" if info.get("is_admin") else f"👤 {username}"
                room = user_rooms.get(username, "")
                if room:
                    display += f" ({room})"
                self.users_listbox.insert(tk.END, display)

        # Rooms
        self.rooms_listbox.delete(0, tk.END)
        for room_name in sorted(rooms.keys()):
            count = len(rooms[room_name])
            locked = "🔒" if room_name in room_passwords else ""
            self.rooms_listbox.insert(tk.END, f"{locked} {room_name} ({count})")

        # Banned users
        self.banned_listbox.delete(0, tk.END)
        for username in sorted(banned):
            self.banned_listbox.insert(tk.END, username)

        # Update stats
        self.stats_var.set(f"Users: {len(clients)} | Rooms: {len(rooms)} | Banned: {len(banned)}")

    def update_status(self, message):
        """Update status label"""
        self.status_var.set(message)

    def periodic_update(self):
        """Periodic UI updates"""
        if self.running:
            self.update_lists()
            self.after(1000, self.periodic_update)

    # ========================================================================
    # CONTEXT MENU HANDLERS
    # ========================================================================

    def on_user_right_click(self, event):
        """Show context menu for users"""
        sel = self.users_listbox.curselection()
        if not sel:
            return

        selected = self.users_listbox.get(sel[0])
        # Extract username (remove emoji and room info)
        username = selected.split()[1] if " " in selected else selected
        username = username.split("(")[0].strip()

        menu = tk.Menu(self, tearoff=0, bg=self.theme['bg_secondary'], fg=self.theme['text_primary'], bd=0, relief=tk.FLAT)
        menu.add_command(label="👢 Kick User", command=lambda: self.quick_kick(username))
        menu.add_command(label="🚫 Ban User", command=lambda: self.quick_ban(username))
        menu.add_command(label="🔇 Mute 30s", command=lambda: self.quick_mute(username, 30))
        menu.add_command(label="🔇 Mute 5min", command=lambda: self.quick_mute(username, 300))
        menu.add_separator()
        menu.add_command(label="📩 Send Message", command=lambda: self.send_to_user(username))
        menu.tk_popup(event.x_root, event.y_root)

    def on_room_right_click(self, event):
        """Show context menu for rooms"""
        sel = self.rooms_listbox.curselection()
        if not sel:
            return

        selected = self.rooms_listbox.get(sel[0])
        room_name = selected.split()[1] if selected.startswith("🔒") else selected.split()[0]

        menu = tk.Menu(self, tearoff=0, bg=self.theme['bg_secondary'], fg=self.theme['text_primary'], bd=0, relief=tk.FLAT)
        menu.add_command(label="🔒 Set Password", command=lambda: self.set_room_password(room_name))
        menu.add_command(label="🔓 Remove Password", command=lambda: self.remove_room_password(room_name))
        menu.add_command(label="👢 Kick All", command=lambda: self.kick_room_users(room_name))
        menu.add_command(label="🗑️ Delete Room", command=lambda: self.delete_room(room_name))
        menu.tk_popup(event.x_root, event.y_root)

    def on_banned_right_click(self, event):
        """Show context menu for banned users"""
        sel = self.banned_listbox.curselection()
        if not sel:
            return

        username = self.banned_listbox.get(sel[0])

        menu = tk.Menu(self, tearoff=0, bg=self.theme['bg_secondary'], fg=self.theme['text_primary'], bd=0, relief=tk.FLAT)
        menu.add_command(label="✅ Unban User", command=lambda: self.quick_unban(username))
        menu.tk_popup(event.x_root, event.y_root)

    # ========================================================================
    # QUICK ACTION FUNCTIONS
    # ========================================================================

    def quick_kick(self, username):
        """Quick kick user"""
        with clients_lock:
            info = clients.get(username)

        if info:
            send_json(info['conn'], {"type": "system", "message": "⚠️ You were kicked by admin."})
            remove_client(username, self)
            self.log(f"Kicked {username}", "admin")
        else:
            self.log(f"User {username} not found", "error")

    def quick_ban(self, username):
        """Quick ban user"""
        banned.add(username)
        save_banned()
        remove_client(username, self)
        self.log(f"Banned {username}", "admin")
        self.update_lists()

    def quick_mute(self, username, seconds):
        """Quick mute user"""
        with clients_lock:
            info = clients.get(username)

        if info:
            info['muted_until'] = time.time() + seconds
            send_json(info['conn'], {"type": "system", "message": f"🔇 You are muted for {seconds} seconds."})
            self.log(f"Muted {username} for {seconds}s", "admin")
        else:
            self.log(f"User {username} not found", "error")

    def quick_unban(self, username):
        """Quick unban user"""
        if username in banned:
            banned.remove(username)
            save_banned()
            self.log(f"Unbanned {username}", "admin")
            self.update_lists()

    def send_to_user(self, username):
        """Send message to specific user"""
        message = simpledialog.askstring(
            "Send Message",
            f"Message to {username}:",
            parent=self
        )

        if message:
            with clients_lock:
                info = clients.get(username)

            if info:
                send_json(info['conn'], {
                    "type": "system",
                    "message": f"📢 Admin: {message}"
                })
                self.log(f"Sent message to {username}: {message}", "admin")

    def set_room_password(self, room_name):
        """Set password for room"""
        password = simpledialog.askstring(
            "Set Password",
            f"Enter password for room '{room_name}':",
            show="•",
            parent=self
        )

        if password:
            room_passwords[room_name] = password
            self.log(f"Set password for room '{room_name}'", "admin")
            self.update_lists()

    def remove_room_password(self, room_name):
        """Remove room password"""
        if room_name in room_passwords:
            del room_passwords[room_name]
            self.log(f"Removed password from room '{room_name}'", "admin")
            self.update_lists()

    def kick_room_users(self, room_name):
        """Kick all users from room"""
        if room_name not in rooms:
            return

        kicked = []
        for username in list(rooms[room_name]):
            remove_client(username, self)
            kicked.append(username)

        self.log(f"Kicked {len(kicked)} users from room '{room_name}'", "admin")

    def delete_room(self, room_name):
        """Delete a room"""
        if room_name in rooms:
            # Kick all users first
            self.kick_room_users(room_name)

            # Remove room data
            if room_name in rooms:
                del rooms[room_name]
            if room_name in room_passwords:
                del room_passwords[room_name]

            self.log(f"Deleted room '{room_name}'", "admin")
            self.update_lists()

    # ========================================================================
    # COMMAND EXECUTION
    # ========================================================================

    def execute_command(self, event=None):
        """Execute admin command"""
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return

        self.cmd_var.set("")
        self.log(f"Admin: {cmd}", "admin")

        parts = cmd.split()
        if not parts:
            return

        cmd0 = parts[0].lower()

        if cmd0 == "/kick" and len(parts) >= 2:
            self.quick_kick(parts[1])

        elif cmd0 == "/ban" and len(parts) >= 2:
            self.quick_ban(parts[1])

        elif cmd0 == "/unban" and len(parts) >= 2:
            self.quick_unban(parts[1])

        elif cmd0 == "/mute" and len(parts) >= 3:
            try:
                self.quick_mute(parts[1], int(parts[2]))
            except ValueError:
                self.log("Invalid seconds value", "error")

        elif cmd0 == "/broadcast" and len(parts) >= 2:
            message = " ".join(parts[1:])
            broadcast({"type": "system", "message": f"📢 Admin: {message}"})
            self.log(f"Broadcast: {message}", "admin")

        elif cmd0 == "/listbans":
            bans = ", ".join(sorted(banned)) if banned else "(none)"
            self.log(f"Banned users: {bans}", "admin")

        elif cmd0 == "/stats":
            with clients_lock:
                total_clients = len(clients)
                admin_count = sum(1 for c in clients.values() if c.get('is_admin'))
            self.log(
                f"Stats: {total_clients} users ({admin_count} admins), "
                f"{len(rooms)} rooms, {len(banned)} banned",
                "admin"
            )

        elif cmd0 == "/help":
            help_text = """
📚 Available Admin Commands:
/kick <user> - Kick user
/ban <user> - Ban user
/unban <user> - Unban user
/mute <user> <sec> - Mute user
/broadcast <msg> - Broadcast message
/listbans - List banned users
/stats - Show server statistics
/serverinfo - Show detailed server info
/clearlog - Clear log display
/help - Show this help
            """
            self.log(help_text.strip(), "system")

        elif cmd0 == "/serverinfo":
            with clients_lock:
                total_clients = len(clients)
                admin_count = sum(1 for c in clients.values() if c.get('is_admin'))
                uptime = sum(time.time() - c.get('joined', time.time()) for c in clients.values())
            
            info_text = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 SERVER INFORMATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 Online Users: {total_clients}
👑 Admin Count: {admin_count}
💬 Active Rooms: {len(rooms)}
🚫 Banned Users: {len(banned)}
⏱️ Total Uptime: {int(uptime // 3600)}h {int((uptime % 3600) // 60)}m
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
            self.log(info_text.strip(), "system")

        elif cmd0 == "/clearlog":
            self.log_display.configure(state=tk.NORMAL)
            self.log_display.delete("1.0", tk.END)
            self.log_display.configure(state=tk.DISABLED)
            self.log(f"✓ Log cleared by admin", "admin")

        else:
            self.log(f"Unknown command: {cmd0}", "error")

    # ========================================================================
    # FILE OPERATIONS
    # ========================================================================

    def save_log_file(self):
        """Save log to file"""
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=f"server_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )

        if not path:
            return

        try:
            self.log_display.configure(state=tk.NORMAL)
            content = self.log_display.get("1.0", tk.END)
            self.log_display.configure(state=tk.DISABLED)

            with open(path, "w", encoding="utf-8") as f:
                f.write("=" * 60 + "\n")
                f.write("PyDiscordish Server Log\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                f.write(content)

            messagebox.showinfo("Success", f"Log saved to:\n{path}")
            self.log(f"Log exported to {path}", "system")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save log:\n{e}")
            self.log(f"Failed to save log: {e}", "error")

    # ========================================================================
    # WINDOW MANAGEMENT
    # ========================================================================

    def on_close(self):
        """Handle window close"""
        if messagebox.askyesno("Confirm Exit", "Are you sure you want to stop the server?"):
            self.running = False

            # Notify all clients
            broadcast({"type": "system", "message": "⚠️ Server is shutting down..."})

            # Close all connections
            with clients_lock:
                for username, info in list(clients.items()):
                    try:
                        info['conn'].close()
                    except:
                        pass

            self.log("Server shutting down...", "system")

            # Give time for cleanup
            self.after(1000, self.destroy)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    try:
        app = ServerGUI()
        app.mainloop()
    except Exception as e:
        print(f"Fatal error: {e}")
        traceback.print_exc()