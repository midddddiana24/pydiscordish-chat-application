import socket
import threading
import json
import time
import queue
import base64
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, simpledialog, messagebox
from tkinter.scrolledtext import ScrolledText
from datetime import datetime

# ============================================================================
# CONFIGURATION
# ============================================================================
SERVER_PORT = 55000
MAX_FILE_SIZE = 200 * 1024  # 200 KB
RECV_BUFFER = 4096
DEFAULT_FONT = "Segoe UI"
FALLBACK_FONT = "Arial"

# Modern color scheme - Modernized Dark Theme Only
MODERN_THEME = {
    'bg_primary': '#0f1419',
    'bg_secondary': '#1a1f2e',
    'bg_tertiary': '#252d3d',
    'accent': '#6366f1',
    'accent_hover': '#818cf8',
    'accent_light': '#e0e7ff',
    'text_primary': '#f8fafc',
    'text_secondary': '#cbd5e1',
    'text_muted': '#94a3b8',
    'success': '#10b981',
    'danger': '#ef4444',
    'warning': '#f59e0b',
    'online': '#34d399',
    'offline': '#64748b',
}


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================
def safe_font(family, size=10, weight="normal"):
    """Create font with fallback support"""
    try:
        return tkfont.Font(family=family, size=size, weight=weight)
    except:
        return tkfont.Font(family=FALLBACK_FONT, size=size, weight=weight)


def format_timestamp(ts=None):
    """Format timestamp in a user-friendly way"""
    if ts is None:
        return datetime.now().strftime("%I:%M %p")
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%I:%M %p")
    except:
        return ts


# ============================================================================
# NETWORK CLIENT
# ============================================================================
class NetClient:
    """Handles all network communication with the server"""

    def __init__(self, host, port, username, incoming_q):
        self.host = host
        self.port = port
        self.username = username
        self.sock = None
        self.incoming = incoming_q
        self.running = False
        self.connected = False

    def connect(self, password, is_register):
        """Connect to server and authenticate"""
        try:
            # Create socket with connection timeout
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)

            # Attempt connection
            self.sock.connect((self.host, self.port))

            # Send authentication immediately
            auth_msg = {
                "type": "auth",
                "username": self.username,
                "password": password,
                "register": is_register
            }

            data = json.dumps(auth_msg, ensure_ascii=False) + "\n"
            self.sock.sendall(data.encode("utf-8"))

            # Set to running and connected
            self.running = True
            self.connected = True

            # Start reader thread
            reader = threading.Thread(target=self.reader_thread, daemon=True)
            reader.start()

            # Remove timeout - let reader thread handle it
            self.sock.settimeout(None)

            # Wait for initial response
            time.sleep(0.2)
            return True

        except socket.timeout:
            self.incoming.put(("system", "Connection timeout: Server not responding"))
            self.running = False
            self.connected = False
            try:
                self.sock.close()
            except:
                pass
            return False
        except ConnectionRefusedError:
            self.incoming.put(("system", f"Connection refused: Server at {self.host}:{self.port} is not running"))
            self.running = False
            self.connected = False
            try:
                self.sock.close()
            except:
                pass
            return False
        except socket.gaierror:
            self.incoming.put(("system", f"Invalid server address: {self.host}"))
            self.running = False
            self.connected = False
            try:
                self.sock.close()
            except:
                pass
            return False
        except Exception as e:
            self.incoming.put(("system", f"Connection failed: {str(e)}"))
            self.running = False
            self.connected = False
            try:
                self.sock.close()
            except:
                pass
            return False

    def send(self, obj):
        """Send JSON message to server"""
        if not self.connected or not self.sock:
            return False
        try:
            data = json.dumps(obj, ensure_ascii=False) + "\n"
            self.sock.sendall(data.encode("utf-8"))
            return True
        except socket.error as e:
            self.incoming.put(("system", f"Send error: {str(e)}"))
            self.connected = False
            self.running = False
            return False
        except Exception as e:
            self.incoming.put(("system", f"Send error: {str(e)}"))
            self.connected = False
            self.running = False
            return False

    def reader_thread(self):
        """Read incoming messages from server"""
        buffer = ""
        try:
            while self.running:
                try:
                    # No timeout - blocking read
                    self.sock.settimeout(None)
                    chunk = self.sock.recv(RECV_BUFFER)

                    if not chunk:
                        # Server closed connection
                        self.incoming.put(("system", "Server closed the connection"))
                        break

                    # Decode received data
                    try:
                        decoded_chunk = chunk.decode('utf-8', errors='replace')
                    except Exception:
                        continue

                    buffer += decoded_chunk

                    # Process complete lines (JSON messages)
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        if line.strip():
                            try:
                                obj = json.loads(line.strip())
                                self.incoming.put(("net", obj))
                            except json.JSONDecodeError:
                                pass

                except socket.error as se:
                    if self.running:
                        self.incoming.put(("system", f"Socket error: {str(se)}"))
                    break
                except Exception as e:
                    if self.running:
                        self.incoming.put(("system", f"Read error: {str(e)}"))
                    break
        except Exception as e:
            if self.running:
                self.incoming.put(("system", f"Reader error: {str(e)}"))
        finally:
            self.connected = False
            self.running = False
            try:
                if self.sock:
                    self.sock.close()
            except:
                pass

    def close(self):
        """Close connection gracefully"""
        self.running = False
        self.connected = False
        try:
            if self.sock:
                self.sock.close()
        except socket.error:
            pass
        except Exception:
            pass


# ============================================================================
# MODERN WIDGETS
# ============================================================================
class ModernButton(tk.Button):
    """Custom styled button with smooth animations and effects"""

    def __init__(self, parent, text="", command=None, style="primary", **kwargs):
        self.style = style
        self.theme = MODERN_THEME
        self.animation_timer = None

        colors = self._get_colors()
        super().__init__(
            parent,
            text=text,
            command=command,
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=10,
            font=safe_font(DEFAULT_FONT, 10, "bold"),
            cursor="hand2",
            **kwargs
        )
        self.configure(
            bg=colors['bg'],
            fg=colors['fg'],
            activebackground=colors['hover'],
            activeforeground=colors['fg']
        )

        # Hover effects
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _get_colors(self):
        if self.style == "primary":
            return {
                'bg': self.theme['accent'],
                'fg': self.theme['text_primary'],
                'hover': self.theme['accent_hover']
            }
        elif self.style == "secondary":
            return {
                'bg': self.theme['bg_tertiary'],
                'fg': self.theme['text_secondary'],
                'hover': self.theme['accent']
            }
        elif self.style == "danger":
            return {
                'bg': self.theme['danger'],
                'fg': self.theme['text_primary'],
                'hover': '#f87171'
            }
        elif self.style == "success":
            return {
                'bg': self.theme['success'],
                'fg': self.theme['text_primary'],
                'hover': '#34d399'
            }
        return {
            'bg': self.theme['bg_secondary'],
            'fg': self.theme['text_primary'],
            'hover': self.theme['bg_tertiary']
        }

    def _on_enter(self, e):
        colors = self._get_colors()
        self.configure(bg=colors['hover'])

    def _on_leave(self, e):
        colors = self._get_colors()
        self.configure(bg=colors['bg'])


# ============================================================================
# MAIN CHAT APPLICATION
# ============================================================================
class ChatApp(tk.Tk):
    """Modern Discord-style chat application"""

    def __init__(self):
        super().__init__()

        # Window setup
        self.title("PyDiscordish - Modern Chat Client")
        self.geometry("1000x650")
        self.minsize(800, 500)

        # State
        self.net = None
        self.incoming = queue.Queue()
        self.username = None
        self.server_ip = None
        self.password = None
        self.avatar = "😊"
        self.chat_log = []
        self.online_users = []
        self.current_target = "All"
        self.typing_state = {}
        self.theme = MODERN_THEME

        # Fonts
        self.font_title = safe_font(DEFAULT_FONT, 16, "bold")
        self.font_header = safe_font(DEFAULT_FONT, 12, "bold")
        self.font_body = safe_font(DEFAULT_FONT, 10)
        self.font_small = safe_font(DEFAULT_FONT, 9)

        # Build UI
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build_ui()

        # Start processing
        self.after(100, self.process_incoming)
        self.after(200, self.show_login_dialog)

        # Try to load notification sound
        try:
            from playsound import playsound
            self._playsound = lambda p: playsound(p, block=False)
        except:
            self._playsound = None

    def _build_ui(self):
        """Build the main user interface"""
        self.configure(bg=self.theme['bg_tertiary'])

        # ===== TOP BAR =====
        self._create_top_bar()

        # ===== MAIN CONTAINER =====
        main_container = tk.Frame(self, bg=self.theme['bg_primary'])
        main_container.pack(expand=True, fill=tk.BOTH)

        # ===== SIDEBAR (LEFT) =====
        self._create_sidebar(main_container)

        # ===== CHAT AREA (RIGHT) =====
        self._create_chat_area(main_container)

    def _create_top_bar(self):
        """Create the top navigation bar with modern design"""
        top_bar = tk.Frame(self, bg=self.theme['bg_tertiary'], height=60, bd=0)
        top_bar.pack(side=tk.TOP, fill=tk.X)
        top_bar.pack_propagate(False)

        # Logo/Title with gradient effect
        title_frame = tk.Frame(top_bar, bg=self.theme['bg_tertiary'])
        title_frame.pack(side=tk.LEFT, padx=20, pady=10)

        tk.Label(
            title_frame,
            text="💬",
            font=safe_font(DEFAULT_FONT, 24),
            bg=self.theme['bg_tertiary'],
            fg=self.theme['accent']
        ).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(
            title_frame,
            text="PyDiscordish",
            font=self.font_title,
            bg=self.theme['bg_tertiary'],
            fg=self.theme['text_primary']
        ).pack(side=tk.LEFT)

        # Status
        self.status_var = tk.StringVar(value="Not connected")
        status_label = tk.Label(
            top_bar,
            textvariable=self.status_var,
            font=self.font_small,
            bg=self.theme['bg_tertiary'],
            fg=self.theme['text_muted']
        )
        status_label.pack(side=tk.RIGHT, padx=20)

        # Action buttons
        btn_frame = tk.Frame(top_bar, bg=self.theme['bg_tertiary'])
        btn_frame.pack(side=tk.RIGHT, padx=10)

        self._create_icon_button(btn_frame, "?", self.show_help_dialog, "Help")
        self._create_icon_button(btn_frame, "💾", self.save_log, "Save chat log")

    def _create_icon_button(self, parent, icon, command, tooltip=""):
        """Create an icon button with smooth hover animation"""
        btn = tk.Button(
            parent,
            text=icon,
            command=command,
            relief=tk.FLAT,
            bd=0,
            bg=self.theme['bg_tertiary'],
            fg=self.theme['text_primary'],
            font=safe_font(DEFAULT_FONT, 16),
            cursor="hand2",
            padx=8,
            pady=4,
            activebackground=self.theme['bg_secondary'],
            activeforeground=self.theme['accent']
        )
        btn.pack(side=tk.RIGHT, padx=4)

        # Smooth hover effects
        def on_enter(e):
            btn.configure(bg=self.theme['bg_secondary'], fg=self.theme['accent'])

        def on_leave(e):
            btn.configure(bg=self.theme['bg_tertiary'], fg=self.theme['text_primary'])

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

        return btn

    def _create_sidebar(self, parent):
        """Create the left sidebar with user list and rooms"""
        sidebar = tk.Frame(parent, width=280, bg=self.theme['bg_secondary'], bd=0)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # User info section
        user_info_frame = tk.Frame(sidebar, bg=self.theme['bg_tertiary'], height=60)
        user_info_frame.pack(fill=tk.X, pady=(0, 8))
        user_info_frame.pack_propagate(False)

        self.user_avatar_label = tk.Label(
            user_info_frame,
            text=self.avatar,
            font=safe_font(DEFAULT_FONT, 20),
            bg=self.theme['bg_tertiary'],
            fg=self.theme['text_primary']
        )
        self.user_avatar_label.pack(side=tk.LEFT, padx=12, pady=10)

        user_text_frame = tk.Frame(user_info_frame, bg=self.theme['bg_tertiary'])
        user_text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=10)

        self.username_label = tk.Label(
            user_text_frame,
            text="Guest",
            font=safe_font(DEFAULT_FONT, 10, "bold"),
            bg=self.theme['bg_tertiary'],
            fg=self.theme['text_primary'],
            anchor="w"
        )
        self.username_label.pack(fill=tk.X)

        self.status_label = tk.Label(
            user_text_frame,
            text="🟢 Online",
            font=self.font_small,
            bg=self.theme['bg_tertiary'],
            fg=self.theme['online'],
            anchor="w"
        )
        self.status_label.pack(fill=tk.X)

        # Scrollable content area
        content_frame = tk.Frame(sidebar, bg=self.theme['bg_secondary'])
        content_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=(0, 8))

        # Online users section
        self._create_section(content_frame, "🟢 Online Users", "users")

        # Rooms section
        self._create_section(content_frame, "💬 Rooms", "rooms")

        # Action buttons (always visible at bottom)
        action_frame = tk.Frame(sidebar, bg=self.theme['bg_secondary'])
        action_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

        ModernButton(
            action_frame,
            text="😊 Emoji",
            command=self.open_emoji_picker,
            style="secondary"
        ).pack(fill=tk.X, pady=3)

        ModernButton(
            action_frame,
            text="📎 File",
            command=self.upload_file,
            style="secondary"
        ).pack(fill=tk.X, pady=3)

    def _create_section(self, parent, title, section_type):
        """Create a collapsible section for users or rooms"""
        # Header
        header = tk.Frame(parent, bg=self.theme['bg_secondary'], height=30)
        header.pack(fill=tk.X, padx=10, pady=(8, 3))
        header.pack_propagate(False)

        tk.Label(
            header,
            text=title,
            font=safe_font(DEFAULT_FONT, 9, "bold"),
            bg=self.theme['bg_secondary'],
            fg=self.theme['text_muted'],
            anchor="w"
        ).pack(side=tk.LEFT, fill=tk.X, padx=5)

        # List container with fixed height
        list_frame = tk.Frame(parent, bg=self.theme['bg_secondary'], height=120)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        list_frame.pack_propagate(False)

        # Scrollable listbox
        listbox = tk.Listbox(
            list_frame,
            font=safe_font(DEFAULT_FONT, 9),
            bg=self.theme['bg_tertiary'],
            fg=self.theme['text_primary'],
            selectbackground=self.theme['accent'],
            selectforeground=self.theme['text_primary'],
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
            cursor="hand2",
            height=6
        )
        listbox.pack(fill=tk.BOTH, expand=True)

        if section_type == "users":
            self.user_listbox = listbox
            listbox.bind("<<ListboxSelect>>", self.on_user_select)
            listbox.insert(tk.END, "📢 All (Public)")
        else:
            self.room_listbox = listbox
            listbox.bind("<<ListboxSelect>>", self.on_room_select)

    def _create_chat_area(self, parent):
        """Create the main chat area"""
        chat_frame = tk.Frame(parent, bg=self.theme['bg_primary'])
        chat_frame.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH)

        # Chat header
        chat_header = tk.Frame(chat_frame, bg=self.theme['bg_tertiary'], height=60, bd=0)
        chat_header.pack(fill=tk.X)
        chat_header.pack_propagate(False)

        self.chat_target_label = tk.Label(
            chat_header,
            text="# general",
            font=self.font_header,
            bg=self.theme['bg_tertiary'],
            fg=self.theme['text_primary'],
            anchor="w"
        )
        self.chat_target_label.pack(side=tk.LEFT, padx=20, pady=15)

        # Messages area
        self.chat_display = ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=self.font_body,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_primary'],
            insertbackground=self.theme['text_primary'],
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
            padx=15,
            pady=10
        )
        self.chat_display.pack(expand=True, fill=tk.BOTH)
        self._configure_chat_tags()

        # Typing indicator
        self.typing_var = tk.StringVar(value="")
        typing_label = tk.Label(
            chat_frame,
            textvariable=self.typing_var,
            font=self.font_small,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_muted'],
            anchor="w"
        )
        typing_label.pack(fill=tk.X, padx=20, pady=(5, 0))

        # Input area
        input_container = tk.Frame(chat_frame, bg=self.theme['bg_primary'], height=80)
        input_container.pack(fill=tk.X, padx=15, pady=15)
        input_container.pack_propagate(False)

        input_frame = tk.Frame(input_container, bg=self.theme['bg_secondary'], bd=0)
        input_frame.pack(fill=tk.BOTH, expand=True)

        self.entry_var = tk.StringVar()
        self.entry = tk.Entry(
            input_frame,
            textvariable=self.entry_var,
            font=self.font_body,
            bg=self.theme['bg_secondary'],
            fg=self.theme['text_primary'],
            insertbackground=self.theme['text_primary'],
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT
        )
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=15, pady=10)
        self.entry.bind("<Return>", self.on_send)
        self.entry.bind("<KeyPress>", self.on_typing)

        send_btn = ModernButton(
            input_frame,
            text="Send ▶",
            command=self.on_send,
            style="primary"
        )
        send_btn.pack(side=tk.RIGHT, padx=10, pady=10)

    def _configure_chat_tags(self):
        """Configure text tags for chat display with modern colors"""
        self.chat_display.tag_configure("timestamp", foreground=self.theme['text_muted'], font=self.font_small)
        self.chat_display.tag_configure("username", foreground=self.theme['accent'], font=self.font_header)
        self.chat_display.tag_configure("system", foreground=self.theme['warning'], font=self.font_body)
        self.chat_display.tag_configure("private", foreground=self.theme['danger'], font=self.font_body)
        self.chat_display.tag_configure("message", foreground=self.theme['text_primary'], font=self.font_body)

    # ========================================================================
    # UI ACTIONS & HANDLERS
    # ========================================================================

    def show_login_dialog(self):
        """Show modern login/register dialog with enhanced design"""
        dialog = tk.Toplevel(self)
        dialog.title("PyDiscordish - Authentication")
        dialog.geometry("480x600")
        dialog.resizable(False, False)
        dialog.configure(bg=self.theme['bg_primary'])
        dialog.transient(self)
        dialog.grab_set()

        # Add shadow effect with darker border
        dialog.attributes('-alpha', 0.99)

        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        # State variable for login/register mode
        is_register_mode = tk.BooleanVar(value=False)

        # Top accent bar
        accent_bar = tk.Frame(dialog, bg=self.theme['accent'], height=3)
        accent_bar.pack(fill=tk.X)
        accent_bar.pack_propagate(False)

        # Header Frame with enhanced design
        header_frame = tk.Frame(dialog, bg=self.theme['bg_secondary'], height=130)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        # Animated logo with glow effect
        logo_frame = tk.Frame(header_frame, bg=self.theme['bg_secondary'])
        logo_frame.pack(pady=(15, 8))

        tk.Label(
            logo_frame,
            text="💬",
            font=safe_font(DEFAULT_FONT, 50),
            bg=self.theme['bg_secondary'],
            fg=self.theme['accent']
        ).pack()

        # Dynamic title label
        title_label = tk.Label(
            header_frame,
            text="PyDiscordish Chat",
            font=safe_font(DEFAULT_FONT, 11, "bold"),
            bg=self.theme['bg_secondary'],
            fg=self.theme['text_primary']
        )
        title_label.pack()

        # Subtitle
        subtitle_label = tk.Label(
            header_frame,
            text="Sign in to your account",
            font=safe_font(DEFAULT_FONT, 8),
            bg=self.theme['bg_secondary'],
            fg=self.theme['text_secondary']
        )
        subtitle_label.pack(pady=(5, 10))

        # Tab Navigation with better styling
        tab_frame = tk.Frame(dialog, bg=self.theme['bg_primary'])
        tab_frame.pack(fill=tk.X, padx=20, pady=(12, 0))

        # Login Tab
        login_tab_btn = tk.Label(
            tab_frame,
            text="🚀 Login",
            font=safe_font(DEFAULT_FONT, 10, "bold"),
            bg=self.theme['bg_primary'],
            fg=self.theme['accent'],
            cursor="hand2",
            pady=10
        )
        login_tab_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Register Tab
        signup_tab_btn = tk.Label(
            tab_frame,
            text="📝 Create Account",
            font=safe_font(DEFAULT_FONT, 10, "bold"),
            bg=self.theme['bg_primary'],
            fg=self.theme['text_muted'],
            cursor="hand2",
            pady=10
        )
        signup_tab_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Underline indicator
        underline = tk.Frame(dialog, bg=self.theme['accent'], height=3)
        underline.pack(fill=tk.X, padx=20)

        # Form container
        form_container = tk.Frame(dialog, bg=self.theme['bg_primary'])
        form_container.pack(padx=25, pady=(12, 10), fill=tk.BOTH, expand=True)

        # Form fields with better styling
        entries = {}
        fields = [
            ("👤 Username", "username", False),
            ("🔒 Password", "password", True),
            ("🌐 Server IP", "server", False)
        ]

        def create_field(parent, label_text, key, is_password):
            field_frame = tk.Frame(parent, bg=self.theme['bg_primary'])
            field_frame.pack(fill=tk.X, pady=(0, 10))

            # Label with icon
            label = tk.Label(
                field_frame,
                text=label_text,
                font=safe_font(DEFAULT_FONT, 9, "bold"),
                bg=self.theme['bg_primary'],
                fg=self.theme['text_primary'],
                anchor="w"
            )
            label.pack(fill=tk.X, pady=(0, 5))

            # Input field with enhanced styling
            entry = tk.Entry(
                field_frame,
                font=self.font_body,
                bg=self.theme['bg_secondary'],
                fg=self.theme['text_primary'],
                insertbackground=self.theme['accent'],
                bd=0,
                relief=tk.FLAT,
                show="•" if is_password else ""
            )
            entry.pack(fill=tk.X, ipady=10, padx=0)
            entries[key] = entry

            # Default values
            if key == "server":
                entry.insert(0, "127.0.0.1")

            # Focus effects with color change
            def on_focus_in(e):
                entry.configure(bg=self.theme['bg_tertiary'])
            
            def on_focus_out(e):
                entry.configure(bg=self.theme['bg_secondary'])

            entry.bind("<FocusIn>", on_focus_in)
            entry.bind("<FocusOut>", on_focus_out)

            return entry

        # Create all fields
        for label_text, key, is_password in fields:
            create_field(form_container, label_text, key, is_password)

        # Avatar Emoji Selector
        avatar_frame = tk.Frame(form_container, bg=self.theme['bg_primary'])
        avatar_frame.pack(fill=tk.X, pady=(0, 10))

        avatar_label = tk.Label(
            avatar_frame,
            text="😊 Select Avatar",
            font=safe_font(DEFAULT_FONT, 9, "bold"),
            bg=self.theme['bg_primary'],
            fg=self.theme['text_primary'],
            anchor="w"
        )
        avatar_label.pack(fill=tk.X, pady=(0, 8))

        # Emoji options
        emoji_options = ["😊", "😎", "🤔", "😍", "🥳", "😴", "😤", "🤗", "😇", "🎭"]
        selected_emoji = tk.StringVar(value="😊")
        entries['avatar'] = selected_emoji

        emoji_btn_frame = tk.Frame(avatar_frame, bg=self.theme['bg_primary'])
        emoji_btn_frame.pack(fill=tk.X)

        for emoji in emoji_options:
            btn = tk.Button(
                emoji_btn_frame,
                text=emoji,
                font=safe_font(DEFAULT_FONT, 14),
                width=4,
                height=1,
                bg=self.theme['bg_secondary'],
                fg=self.theme['text_primary'],
                relief=tk.FLAT,
                bd=0,
                cursor="hand2",
                command=lambda e=emoji: selected_emoji.set(e),
                activebackground=self.theme['accent'],
                activeforeground=self.theme['text_primary']
            )
            btn.pack(side=tk.LEFT, padx=2, fill=tk.BOTH, expand=True)
            
            # Bind hover effects
            def on_emoji_enter(event, button=btn):
                button.config(bg=self.theme['accent_hover'])
            
            def on_emoji_leave(event, button=btn):
                if selected_emoji.get() != event.widget.cget("text"):
                    button.config(bg=self.theme['bg_secondary'])
            
            btn.bind("<Enter>", on_emoji_enter)
            btn.bind("<Leave>", on_emoji_leave)

        # Update button colors when emoji is selected
        def update_emoji_colors():
            for child in emoji_btn_frame.winfo_children():
                emoji_text = child.cget("text")
                if emoji_text == selected_emoji.get():
                    child.config(bg=self.theme['accent'])
                else:
                    child.config(bg=self.theme['bg_secondary'])
        
        # Call update when selection changes
        selected_emoji.trace("w", lambda *args: update_emoji_colors())

        # Buttons container
        btn_container = tk.Frame(dialog, bg=self.theme['bg_primary'])
        btn_container.pack(pady=(0, 10), padx=25, fill=tk.X)

        # Primary action button with enhanced styling
        action_btn = ModernButton(
            btn_container,
            text="🚀 Login",
            command=None,  # Will be set by toggle function
            style="primary"
        )
        action_btn.pack(fill=tk.X, pady=(0, 8), ipady=4)

        def toggle_mode(is_signup=None):
            """Toggle between login and register mode with smooth animations"""
            if is_signup is not None:
                is_register_mode.set(is_signup)
            else:
                current_mode = is_register_mode.get()
                is_register_mode.set(not current_mode)

            if is_register_mode.get():
                # Switch to Register mode
                title_label.config(text="PyDiscordish Chat")
                subtitle_label.config(text="Create your account")
                action_btn.config(text="📝 Create Account")

                # Update tab buttons styling
                login_tab_btn.config(
                    fg=self.theme['text_secondary']
                )
                signup_tab_btn.config(
                    fg=self.theme['accent']
                )
                underline.pack_configure(padx=(20 + 280, 20))  # Move underline to right
            else:
                # Switch to Login mode
                title_label.config(text="PyDiscordish Chat")
                subtitle_label.config(text="Sign in to your account")
                action_btn.config(text="🚀 Login")

                # Update tab buttons styling
                login_tab_btn.config(
                    fg=self.theme['accent']
                )
                signup_tab_btn.config(
                    fg=self.theme['text_secondary']
                )
                underline.pack_configure(padx=(20, 20 + 280))  # Move underline to left

        # Setup tab button click handlers
        login_tab_btn.bind("<Button-1>", lambda e: toggle_mode(False))
        signup_tab_btn.bind("<Button-1>", lambda e: toggle_mode(True))

        # Hover effects for tab buttons
        def on_tab_enter(btn):
            def handler(e):
                btn.config(font=safe_font(DEFAULT_FONT, 11, "bold"))
            return handler

        def on_tab_leave(btn):
            def handler(e):
                btn.config(font=safe_font(DEFAULT_FONT, 11, "bold"))
            return handler

        login_tab_btn.bind("<Enter>", on_tab_enter(login_tab_btn))
        login_tab_btn.bind("<Leave>", on_tab_leave(login_tab_btn))
        signup_tab_btn.bind("<Enter>", on_tab_enter(signup_tab_btn))
        signup_tab_btn.bind("<Leave>", on_tab_leave(signup_tab_btn))

        # Help text section
        help_frame = tk.Frame(dialog, bg=self.theme['bg_primary'])
        help_frame.pack(fill=tk.X, padx=25, pady=(0, 10))

        help_text = tk.Label(
            help_frame,
            text="💡 Default: 127.0.0.1:55000",
            font=safe_font(DEFAULT_FONT, 7),
            bg=self.theme['bg_primary'],
            fg=self.theme['text_muted'],
            wraplength=350,
            justify=tk.LEFT
        )
        help_text.pack(fill=tk.X)

        def validate_and_connect():
            """Validate inputs and connect to server"""
            self.username = entries['username'].get().strip()
            self.password = entries['password'].get().strip()
            self.server_ip = entries['server'].get().strip()
            self.avatar = entries['avatar'].get() or "😊"

            # Validation
            if not self.username:
                messagebox.showerror("Validation Error", "Username is required!", parent=dialog)
                entries['username'].focus()
                return

            if len(self.username) < 3:
                messagebox.showerror("Validation Error", "Username must be at least 3 characters!", parent=dialog)
                entries['username'].focus()
                return

            if not self.password:
                messagebox.showerror("Validation Error", "Password is required!", parent=dialog)
                entries['password'].focus()
                return

            if len(self.password) < 4:
                messagebox.showerror("Validation Error", "Password must be at least 4 characters!", parent=dialog)
                entries['password'].focus()
                return

            if not self.server_ip:
                messagebox.showerror("Validation Error", "Server IP is required!", parent=dialog)
                entries['server'].focus()
                return

            # Disable button to prevent double-click
            action_btn.config(state=tk.DISABLED, text="Connecting...")
            dialog.update()

            # Connect with appropriate mode
            dialog.destroy()
            self.connect_network(is_register_mode.get())

        # Set the action button command
        action_btn.config(command=validate_and_connect)

        # Bind Enter key to connect
        for entry in entries.values():
            entry.bind("<Return>", lambda e: validate_and_connect())

        # Focus on username field
        entries['username'].focus()

    def connect_network(self, is_register):
        """Connect to the chat server"""
        # Show loading indicator
        self.status_var.set("Connecting...")
        self.update()

        self.net = NetClient(self.server_ip, SERVER_PORT, self.username, self.incoming)

        try:
            # Attempt connection
            if self.net.connect(self.password, is_register):
                # Wait for auth response
                time.sleep(0.5)

                if is_register:
                    # Registration successful - show message and reconnect for login
                    messagebox.showinfo(
                        "Registration Successful!",
                        f"Account '{self.username}' has been created!\n\nPlease login with your credentials."
                    )
                    self.net.close()
                    self.after(500, self.show_login_dialog)
                else:
                    # Login successful
                    self.status_var.set(f"Connected to {self.server_ip}:{SERVER_PORT}")
                    self.username_label.config(text=self.username)
                    self.user_avatar_label.config(text=self.avatar)
                    self.append_system(f"✅ Successfully logged in as {self.username}")
                    self.append_system("Type /help to see available commands")
            else:
                # Connection failed
                time.sleep(0.3)

                error_msg = "Could not connect to server. Please check:\n\n"
                error_msg += "• Server is running\n"
                error_msg += "• Server IP is correct\n"
                error_msg += "• Network connection is active"

                if not is_register:
                    error_msg += "\n• Username and password are correct"

                messagebox.showerror("Connection Failed", error_msg)
                self.after(100, self.show_login_dialog)

        except Exception as e:
            messagebox.showerror(
                "Connection Error",
                f"An unexpected error occurred:\n\n{str(e)}"
            )
            self.after(100, self.show_login_dialog)

    def toggle_theme(self):
        """Removed - Single modern theme only"""
        pass

    def _update_widget_theme(self, widget):
        """Removed - Single modern theme only"""
        pass

    def on_user_select(self, event):
        """Handle user selection from list"""
        sel = self.user_listbox.curselection()
        if sel:
            selected = self.user_listbox.get(sel[0])
            if selected.startswith("📢"):
                self.current_target = "All"
                self.chat_target_label.config(text="# general (public)")
            else:
                # Remove any emoji prefixes
                self.current_target = selected.split()[-1] if " " in selected else selected
                self.chat_target_label.config(text=f"@ {self.current_target} (private)")

    def on_room_select(self, event):
        """Handle room selection"""
        sel = self.room_listbox.curselection()
        if not sel:
            return

        room = self.room_listbox.get(sel[0]).split()[0]
        pwd = simpledialog.askstring(
            "Room Password",
            f"Enter password for '{room}' (leave blank if none):",
            show="•",
            parent=self
        )

        if pwd is not None:  # User didn't cancel
            if self.net:
                self.net.send({"type": "command", "command": f"/join {room} {pwd}"})

    def on_typing(self, event=None):
        """Handle typing indicator"""
        if not self.net or not self.net.connected:
            return

        try:
            self.net.send({"type": "typing", "status": True})
            # Cancel previous timer
            if hasattr(self, '_typing_timer'):
                self.after_cancel(self._typing_timer)
            # Set new timer to stop typing after 1.5s
            self._typing_timer = self.after(1500, self.send_typing_stop)
        except:
            pass

    def send_typing_stop(self):
        """Stop typing indicator"""
        if self.net and self.net.connected:
            try:
                self.net.send({"type": "typing", "status": False})
            except:
                pass

    def show_help(self, command_filter=None):
        """Display help dialog with available commands"""
        help_dialog = tk.Toplevel(self)
        help_dialog.title("Command Help - PyDiscordish")
        help_dialog.geometry("600x500")
        help_dialog.configure(bg=self.theme['bg_secondary'])
        help_dialog.transient(self)
        help_dialog.grab_set()

        # Center the dialog
        help_dialog.update_idletasks()
        x = (help_dialog.winfo_screenwidth() // 2) - (help_dialog.winfo_width() // 2)
        y = (help_dialog.winfo_screenheight() // 2) - (help_dialog.winfo_height() // 2)
        help_dialog.geometry(f"+{x}+{y}")

        # Header
        header_frame = tk.Frame(help_dialog, bg=self.theme['bg_tertiary'], height=60)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        tk.Label(
            header_frame,
            text="📚 Command Help",
            font=self.font_title,
            bg=self.theme['bg_tertiary'],
            fg=self.theme['text_primary']
        ).pack(pady=15)

        # Scrollable text area for commands
        text_frame = tk.Frame(help_dialog, bg=self.theme['bg_secondary'])
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        help_text = ScrolledText(
            text_frame,
            wrap=tk.WORD,
            font=self.font_body,
            bg=self.theme['bg_primary'],
            fg=self.theme['text_primary'],
            insertbackground=self.theme['text_primary'],
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
            padx=15,
            pady=10
        )
        help_text.pack(fill=tk.BOTH, expand=True)

        # Define help content
        help_content = """
🎯 BASIC COMMANDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/help or /?
  Shows this help menu with all available commands

/list or /users
  Display all online users in the chat

/pm <username> <message>
  Send a private message to a specific user
  Example: /pm John Hello there!

/me <action>
  Send an action message
  Example: /me is thinking...


👥 USER & ROOM COMMANDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/whoami
  Display your current username

/create <room_name> [password]
  Create a new chat room
  Example: /create gaming secret123

/join <room_name> [password]
  Join an existing room
  Example: /join gaming secret123

/leave
  Leave the current room and return to public chat

/rooms
  List all available chat rooms


⚙️ ADMIN COMMANDS (Admin Only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/kick <username>
  Remove a user from the server

/ban <username>
  Ban a user from the server

/unban <username>
  Remove a user from the ban list

/mute <username>
  Prevent a user from sending messages

/unmute <username>
  Allow a previously muted user to chat

/announce <message>
  Send a server-wide announcement


💡 USAGE TIPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Type messages normally for public broadcast
• Select a user from the sidebar to send private messages
• Use /help <command> for detailed info on a specific command
• Commands are case-insensitive
• File sharing available via "Upload File" button
• Use emoji picker for quick emoji insertion


❓ NEED MORE HELP?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For issues or questions:
• Check the command syntax carefully
• Ensure you're connected to the server
• Try refreshing your user list (/list)
• Contact a server administrator
"""

        help_text.configure(state=tk.NORMAL)
        help_text.insert(tk.END, help_content)
        help_text.configure(state=tk.DISABLED)
        help_text.see("1.0")

        # Close button
        button_frame = tk.Frame(help_dialog, bg=self.theme['bg_secondary'])
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        ModernButton(
            button_frame,
            text="Close",
            command=help_dialog.destroy,
            style="primary"
        ).pack(fill=tk.X)

    def on_send(self, event=None):
        """Handle message send"""
        text = self.entry_var.get().strip()
        if not text or not self.net or not self.net.connected:
            return

        # Clear input immediately for better UX
        self.entry_var.set("")

        # Handle commands - check for help first
        if text.startswith("/"):
            # Handle /help and /? locally
            cmd = text.split()[0].lower()
            
            if cmd == "/help" or cmd == "/?":
                # Show help dialog
                self.show_help()
                self.send_typing_stop()
                return
            else:
                # Send other commands to server
                self.net.send({"type": "command", "command": text})
                self.send_typing_stop()
                return

        # Send message
        target = self.current_target or "All"
        ts = format_timestamp()

        if target == "All":
            self.net.send({"type": "broadcast", "message": text})
            self.append_message(ts, self.username, text, is_own=True)
        else:
            self.net.send({"type": "private", "to": target, "message": text})
            self.append_message(ts, f"{self.username} → {target}", text, is_own=True, is_private=True)

        self.send_typing_stop()

    def append_system(self, text):
        """Append system message to chat"""
        self.chat_display.configure(state=tk.NORMAL)
        ts = format_timestamp()
        self.chat_display.insert(tk.END, f"[{ts}] ", "timestamp")
        self.chat_display.insert(tk.END, f"⚙️ {text}\n", "system")
        self.chat_display.configure(state=tk.DISABLED)
        self.chat_display.see(tk.END)

        full_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.chat_log.append((full_ts, "SYSTEM", text, None))

    def append_message(self, ts, sender, message, is_own=False, is_private=False):
        """Append chat message to display"""
        self.chat_display.configure(state=tk.NORMAL)

        # Add spacing between messages
        self.chat_display.insert(tk.END, "\n")

        # Avatar and sender
        avatar = self.avatar if is_own else "👤"
        self.chat_display.insert(tk.END, f"{avatar} ", "message")
        self.chat_display.insert(tk.END, sender, "username")
        self.chat_display.insert(tk.END, f"  {ts}", "timestamp")

        if is_private:
            self.chat_display.insert(tk.END, " 🔒", "private")

        self.chat_display.insert(tk.END, "\n")

        # Message content
        self.chat_display.insert(tk.END, f"  {message}\n", "message")

        self.chat_display.configure(state=tk.DISABLED)
        self.chat_display.see(tk.END)

        full_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.chat_log.append((full_ts, sender, message, "private" if is_private else None))

    def process_incoming(self):
        """Process incoming messages from server"""
        try:
            while True:
                try:
                    tag, payload = self.incoming.get_nowait()
                except queue.Empty:
                    break

                try:
                    if tag == "system":
                        self.append_system(payload)
                        self.play_notification()

                    elif tag == "net":
                        if isinstance(payload, dict):
                            self.handle_server_message(payload)
                except Exception as e:
                    # Log but don't crash on message handling errors
                    self.append_system(f"Error processing message: {str(e)}")

        except Exception as e:
            # Catch any unexpected errors in queue processing
            self.append_system(f"Queue processing error: {str(e)}")

        # Schedule next check
        if self.net and self.net.connected:
            self.after(100, self.process_incoming)
        else:
            # Retry connection prompt after longer delay
            self.after(2000, self.check_reconnect)

    def handle_server_message(self, obj):
        """Handle different types of server messages"""
        mtype = obj.get("type")

        if mtype == "system":
            self.append_system(obj.get("message", ""))
            self.play_notification()

        elif mtype == "broadcast":
            ts = format_timestamp(obj.get("timestamp"))
            sender = obj.get("from", "Unknown")
            message = obj.get("message", "")
            self.append_message(ts, sender, message)
            if sender != self.username:
                self.play_notification()

        elif mtype == "private":
            ts = format_timestamp(obj.get("timestamp"))
            sender = obj.get("from", "Unknown")
            message = obj.get("message", "")
            self.append_message(ts, sender, message, is_private=True)
            if sender != self.username:
                self.play_notification()

        elif mtype == "userlist":
            users = obj.get("users", [])
            rooms = obj.get("rooms", {})
            self.update_userlist(users)
            self.update_roomlist(rooms)

        elif mtype == "typing":
            user = obj.get("user")
            status = obj.get("status", False)
            if user and user != self.username:
                self.typing_state[user] = status
                self.refresh_typing_indicator()

        elif mtype == "file":
            ts = format_timestamp(obj.get("timestamp"))
            sender = obj.get("from", "Unknown")
            filename = obj.get("filename", "unknown")
            size = obj.get("size", 0)
            self.append_message(ts, sender, f"📎 Sent file: {filename} ({size} bytes)")
            self.play_notification()

    def refresh_typing_indicator(self):
        """Update typing indicator display"""
        active = [u for u, s in self.typing_state.items() if s]
        if active:
            if len(active) == 1:
                self.typing_var.set(f"✏️ {active[0]} is typing...")
            elif len(active) == 2:
                self.typing_var.set(f"✏️ {active[0]} and {active[1]} are typing...")
            else:
                self.typing_var.set(f"✏️ {len(active)} people are typing...")
        else:
            self.typing_var.set("")

    def update_userlist(self, users):
        """Update the online users list"""
        self.user_listbox.delete(0, tk.END)
        self.user_listbox.insert(tk.END, "📢 All (Public)")

        for user in sorted(users):
            if user != self.username:
                display = f"👤 {user}"
                self.user_listbox.insert(tk.END, display)

        self.online_users = users

    def update_roomlist(self, rooms):
        """Update the rooms list"""
        self.room_listbox.delete(0, tk.END)

        if rooms:
            for room_name in sorted(rooms.keys()):
                member_count = len(rooms[room_name])
                display = f"💬 {room_name} ({member_count})"
                self.room_listbox.insert(tk.END, display)
        else:
            self.room_listbox.insert(tk.END, "(No rooms yet)")

    def check_reconnect(self):
        """Check if reconnection is needed"""
        if not self.net or not self.net.connected:
            response = messagebox.askyesno(
                "Disconnected",
                "Connection to server lost. Try to reconnect?"
            )
            if response:
                self.show_login_dialog()
            else:
                self.destroy()

    def show_help_dialog(self):
        """Show help dialog with available commands and features"""
        help_window = tk.Toplevel(self)
        help_window.title("PyDiscordish - Help & Commands")
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
            text="?",
            font=safe_font(DEFAULT_FONT, 24),
            bg=self.theme['bg_secondary'],
            fg=self.theme['accent']
        ).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(
            title_frame,
            text="Help & Commands",
            font=safe_font(DEFAULT_FONT, 14, "bold"),
            bg=self.theme['bg_secondary'],
            fg=self.theme['text_primary']
        ).pack(side=tk.LEFT)

        # Scrollable content
        help_text = ScrolledText(
            help_window,
            wrap=tk.WORD,
            font=safe_font(DEFAULT_FONT, 9),
            bg=self.theme['bg_primary'],
            fg=self.theme['text_primary'],
            bd=0,
            relief=tk.FLAT,
            padx=15,
            pady=15
        )
        help_text.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

        commands_info = """🎯 BASIC COMMANDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/help or /?  → Show all available commands
/list or /users  → Show online users
/whoami  → Show your username
/me <action>  → Send action message

💬 ROOM MANAGEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/create <room> [pwd]  → Create a new room
/join <room> [pwd]  → Join a room
/leave  → Leave your current room
/rooms  → List all available rooms

💻 PRIVATE MESSAGING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Right-click on a username in the user list
to send a private message.

🎭 AVATAR & PROFILE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Select your avatar emoji when logging in.
Your avatar will display in the chat.

👑 ADMIN COMMANDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/admin <password>  → Become an admin

Once admin, you can use:
/kick <user>  → Remove user
/ban <user>  → Ban user
/unban <user>  → Unban user
/mute <user> <sec>  → Mute user
/announce <msg>  → Send announcement

💡 TIPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Use Tab key to move between fields
• Press Enter to send messages
• Click usernames to reply to them
• Use emojis in your messages! 😊
• Commands are case-insensitive

🌐 DEFAULT SERVER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Host: 127.0.0.1
Port: 55000

Contact your server admin for other servers!

👨‍💻 ABOUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PyDiscordish Chat Application
Developed by: GODDDOG

A modern, feature-rich chat application
with rooms, admin controls, and more!

Version: 1.0
© 2025 All Rights Reserved"""

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

    def save_log(self):
        """Save chat log to file"""
        if not self.chat_log:
            messagebox.showinfo("No Messages", "No chat messages to save.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )

        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"PyDiscordish Chat Log\n")
                f.write(f"User: {self.username}\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")

                for ts, sender, msg, priv in self.chat_log:
                    if priv:
                        f.write(f"[{ts}] {sender} (private): {msg}\n")
                    else:
                        f.write(f"[{ts}] {sender}: {msg}\n")

            messagebox.showinfo("Success", f"Chat log saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save log:\n{e}")

    def upload_file(self):
        """Upload file to server"""
        path = filedialog.askopenfilename(title="Select file to upload")
        if not path:
            return

        try:
            size = os.path.getsize(path)
            if size > MAX_FILE_SIZE:
                messagebox.showerror(
                    "File Too Large",
                    f"File must be smaller than {MAX_FILE_SIZE // 1024} KB"
                )
                return

            with open(path, "rb") as f:
                raw = f.read()

            b64 = base64.b64encode(raw).decode("ascii")
            filename = os.path.basename(path)
            target = self.current_target or "All"

            if self.net and self.net.connected:
                self.net.send({
                    "type": "file",
                    "to": target,
                    "filename": filename,
                    "data": b64,
                    "size": len(raw)
                })

                ts = format_timestamp()
                self.append_message(
                    ts,
                    self.username,
                    f"📎 Uploaded: {filename} ({len(raw)} bytes)",
                    is_own=True
                )
            else:
                messagebox.showerror("Error", "Not connected to server")

        except Exception as e:
            messagebox.showerror("Upload Failed", f"Could not upload file:\n{e}")

    def open_emoji_picker(self):
        """Open emoji picker dialog"""
        dialog = tk.Toplevel(self)
        dialog.title("Emoji Picker")
        dialog.geometry("400x300")
        dialog.configure(bg=self.theme['bg_secondary'])
        dialog.transient(self)

        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        tk.Label(
            dialog,
            text="Select an Emoji",
            font=self.font_header,
            bg=self.theme['bg_secondary'],
            fg=self.theme['text_primary']
        ).pack(pady=15)

        # Emoji grid
        emojis = [
            "😀", "😃", "😄", "😁", "😆", "😅", "🤣", "😂",
            "🙂", "😊", "😇", "😍", "🤩", "😘", "😗", "😙",
            "😋", "😛", "😜", "🤪", "😝", "🤑", "🤗", "🤭",
            "🤔", "🤐", "🤨", "😐", "😑", "😶", "😏", "😒",
            "🙄", "😬", "🤥", "😌", "😔", "😪", "🤤", "😴",
            "👍", "👎", "👌", "✌️", "🤞", "🤟", "🤘", "🤙",
            "👏", "🙌", "👐", "🤲", "🤝", "🙏", "✍️", "💪",
            "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍"
        ]

        emoji_frame = tk.Frame(dialog, bg=self.theme['bg_secondary'])
        emoji_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=10)

        def select_emoji(emoji):
            current = self.entry_var.get()
            self.entry_var.set(current + emoji)
            dialog.destroy()

        # Create grid of emoji buttons
        for i, emoji in enumerate(emojis):
            row = i // 8
            col = i % 8
            btn = tk.Button(
                emoji_frame,
                text=emoji,
                font=safe_font(DEFAULT_FONT, 20),
                command=lambda e=emoji: select_emoji(e),
                relief=tk.FLAT,
                bd=0,
                bg=self.theme['bg_secondary'],
                fg=self.theme['text_primary'],
                cursor="hand2",
                width=2,
                height=1
            )
            btn.grid(row=row, column=col, padx=2, pady=2)

            # Hover effect
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=self.theme['bg_tertiary']))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=self.theme['bg_secondary']))

    def play_notification(self):
        """Play notification sound"""
        try:
            if self._playsound:
                # Add sound file path if available
                pass
            else:
                self.bell()
        except:
            pass

    def on_close(self):
        """Handle window close"""
        if self.net:
            try:
                self.net.close()
            except:
                pass
        self.destroy()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    try:
        app = ChatApp()
        app.mainloop()
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback

        traceback.print_exc()