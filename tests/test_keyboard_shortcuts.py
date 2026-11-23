import shutil
import subprocess
from pathlib import Path
import pytest

from utils.keyboard_shortcuts_service import (
    get_keyboard_shortcuts,
    KeyboardShortcutHandler,
)


def test_keyboard_shortcuts():
    """Verifies that platform shortcuts registry returns navigation, search, and action items."""
    shortcuts = get_keyboard_shortcuts()
    assert len(shortcuts) >= 2

    # Check categories
    categories = [cat["category"] for cat in shortcuts]
    assert "Global Navigation" in categories

    # Check key shortcuts
    all_bindings = []
    for cat in shortcuts:
        for s in cat.get("shortcuts", []):
            all_bindings.append((tuple(s.get("keys", [])), s.get("url")))

    keys_list = [b[0] for b in all_bindings]
    assert ("g", "d") in keys_list
    assert ("g", "i") in keys_list
    assert ("g", "t") in keys_list
    assert ("g", "c") in keys_list
    assert ("/",) in keys_list
    assert ("?",) in keys_list
    assert ("Escape",) in keys_list
    assert ("Control", "Enter") in keys_list


def test_keyboard_shortcuts_api(client):
    """Verifies GET /api/shortcuts returns 200 with platform shortcut definitions."""
    res = client.get("/api/shortcuts")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert len(data["shortcuts"]) >= 2

    nav_cat = next(
        (c for c in data["shortcuts"] if c["category"] == "Global Navigation"), None
    )
    assert nav_cat is not None
    nav_keys = [s["keys"] for s in nav_cat["shortcuts"]]
    assert ["g", "d"] in nav_keys
    assert ["g", "i"] in nav_keys
    assert ["g", "t"] in nav_keys
    assert ["g", "c"] in nav_keys


def test_shortcut_target_routes_exist(client):
    """Verifies that all shortcut destination URLs resolve without 404 errors (#691)."""
    # Dashboard: / and /dashboard
    res_root = client.get("/")
    assert res_root.status_code == 200

    res_dash = client.get("/dashboard")
    assert res_dash.status_code in (200, 301, 302)

    # Interview practice: /interview
    res_interview = client.get("/interview")
    assert res_interview.status_code in (200, 301, 302)

    # Tracker: /tracker and /applications
    res_tracker = client.get("/tracker")
    assert res_tracker.status_code in (200, 301, 302)
    res_apps = client.get("/applications")
    assert res_apps.status_code in (200, 301, 302)

    # Coding practice: /practice and /coding-practice
    res_practice = client.get("/practice")
    assert res_practice.status_code in (200, 301, 302)
    res_coding = client.get("/coding-practice")
    assert res_coding.status_code in (200, 301, 302)


def test_key_handler_state_machine_simulated_sequences():
    """
    Tests simulated key event sequence handler logic (#691):
    g d -> /
    g i -> /interview
    g t -> /applications
    g c -> /coding-practice
    /   -> focus_search
    ?   -> open_help
    Esc -> close_dialog
    """
    handler = KeyboardShortcutHandler()

    # 1. 'g' then 'd' -> navigate to '/'
    action1, val1 = handler.handle_key("g")
    assert action1 is None
    assert val1 is None
    assert handler.pending_key == "g"

    action2, val2 = handler.handle_key("d")
    assert action2 == "navigate"
    assert val2 == "/"
    assert handler.pending_key is None

    # 2. 'g' then 'i' -> navigate to '/interview'
    handler.handle_key("g")
    action, val = handler.handle_key("i")
    assert action == "navigate"
    assert val == "/interview"

    # 3. 'g' then 't' -> navigate to '/applications'
    handler.handle_key("g")
    action, val = handler.handle_key("t")
    assert action == "navigate"
    assert val == "/applications"

    # 4. 'g' then 'c' -> navigate to '/coding-practice'
    handler.handle_key("g")
    action, val = handler.handle_key("c")
    assert action == "navigate"
    assert val == "/coding-practice"

    # 5. Alternate keys (g h, g p, g a)
    handler.handle_key("g")
    assert handler.handle_key("h") == ("navigate", "/")

    handler.handle_key("g")
    assert handler.handle_key("p") == ("navigate", "/coding-practice")

    handler.handle_key("g")
    assert handler.handle_key("a") == ("navigate", "/applications")

    # 6. 'g' then unrecognized key -> None, state cleared
    handler.handle_key("g")
    action_unrec, val_unrec = handler.handle_key("x")
    assert action_unrec is None
    assert val_unrec is None
    assert handler.pending_key is None

    # 7. Single key actions
    assert handler.handle_key("/") == ("focus_search", None)
    assert handler.handle_key("?") == ("open_help", None)
    assert handler.handle_key("Escape") == ("close_dialog", None)
    assert handler.handle_key("Esc") == ("close_dialog", None)


def test_key_handler_ignores_typing_in_form_fields():
    """Verifies that shortcuts do nothing while typing in an input, textarea, or contenteditable."""
    handler = KeyboardShortcutHandler()

    # Input text
    action, _ = handler.handle_key("g", tag_name="input", input_type="text")
    assert action is None
    assert handler.pending_key is None

    action, _ = handler.handle_key("/", tag_name="input", input_type="text")
    assert action is None

    action, _ = handler.handle_key("?", tag_name="input", input_type="email")
    assert action is None

    # Textarea
    action, _ = handler.handle_key("g", tag_name="textarea")
    assert action is None
    assert handler.pending_key is None

    # Select
    action, _ = handler.handle_key("g", tag_name="select")
    assert action is None

    # Contenteditable
    action, _ = handler.handle_key("g", is_content_editable=True)
    assert action is None
    action, _ = handler.handle_key("/", is_content_editable=True)
    assert action is None

    # Non-typing inputs (e.g. buttons) should NOT be considered typing fields
    assert handler.is_editable("input", input_type="button") is False
    assert handler.is_editable("input", input_type="submit") is False
    assert handler.is_editable("input", input_type="checkbox") is False


def test_key_handler_ignores_modifiers_and_preserves_ctrl_enter():
    """
    Verifies that modifier keys (Ctrl, Alt, Meta) are ignored,
    guaranteeing no conflicts with existing shortcuts like Ctrl+Enter to submit.
    """
    handler = KeyboardShortcutHandler()

    # Ctrl+Enter (submit answer / run code)
    action, val = handler.handle_key("Enter", ctrl_key=True)
    assert action is None
    assert val is None
    assert handler.pending_key is None

    # Ctrl+c (copy)
    action, val = handler.handle_key("c", ctrl_key=True)
    assert action is None
    assert val is None

    # Alt+d (browser address bar on some systems)
    action, val = handler.handle_key("d", alt_key=True)
    assert action is None

    # Meta+k (command palette)
    action, val = handler.handle_key("k", meta_key=True)
    assert action is None

    # If pending 'g' was active, pressing Ctrl cancels sequence
    handler.handle_key("g")
    assert handler.pending_key == "g"
    action, _ = handler.handle_key("d", ctrl_key=True)
    assert action is None
    assert handler.pending_key is None


def test_shortcuts_help_modal_rendered_in_templates(client):
    """Verifies that the shortcuts help dialog is properly included in rendered pages."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Modal accessibility attributes
    assert 'id="shortcutsHelpModal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="shortcutsHelpModalTitle"' in html

    # Accessible close button
    assert 'id="shortcutsHelpCloseBtn"' in html
    assert 'aria-label="Close keyboard shortcuts dialog"' in html

    # Shortcuts listed
    assert "shortcut-kbd" in html
    assert "Dashboard" in html
    assert "Mock Interview Practice" in html
    assert "Application Tracker" in html
    assert "Coding Practice" in html
    assert "Focus Search" in html


def test_javascript_key_handler_simulated_dom_execution():
    """
    Executes simulated DOM key events on the actual JavaScript module
    using Node.js (when available in environment) to verify browser behavior.
    """
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js not available in current test environment.")

    js_file = Path("static/js/modules/keyboard_shortcuts.js").resolve()
    assert js_file.exists(), "keyboard_shortcuts.js must exist."

    # Node script simulating browser DOM environment, elements, and KeyboardEvents
    test_script = f"""
    import {{
      KEYBOARD_NAVIGATION_MAP,
      isTypingElement,
      findSearchInput,
      ensureShortcutsModal,
      handleKeydownEvent
    }} from {repr(js_file.as_uri())};
    import assert from 'node:assert';

    // Mock minimal DOM
    let currentUrl = '/';
    const mockNavigate = (url) => {{ currentUrl = url; }};

    // 1. Test navigation sequences
    let prevented = false;
    const fakeEvent = (key, opts = {{}}) => ({{
      key,
      ctrlKey: opts.ctrlKey || false,
      altKey: opts.altKey || false,
      metaKey: opts.metaKey || false,
      shiftKey: opts.shiftKey || false,
      target: opts.target || {{ tagName: 'BODY', getAttribute: () => null }},
      preventDefault: () => {{ prevented = true; }}
    }});

    // 'g' then 'd'
    handleKeydownEvent(fakeEvent('g'), {{ navigate: mockNavigate }});
    handleKeydownEvent(fakeEvent('d'), {{ navigate: mockNavigate }});
    assert.strictEqual(currentUrl, '/', 'g d should navigate to /');

    // 'g' then 'i'
    handleKeydownEvent(fakeEvent('g'), {{ navigate: mockNavigate }});
    handleKeydownEvent(fakeEvent('i'), {{ navigate: mockNavigate }});
    assert.strictEqual(currentUrl, '/interview', 'g i should navigate to /interview');

    // 'g' then 't'
    handleKeydownEvent(fakeEvent('g'), {{ navigate: mockNavigate }});
    handleKeydownEvent(fakeEvent('t'), {{ navigate: mockNavigate }});
    assert.strictEqual(currentUrl, '/applications', 'g t should navigate to /applications');

    // 'g' then 'c'
    handleKeydownEvent(fakeEvent('g'), {{ navigate: mockNavigate }});
    handleKeydownEvent(fakeEvent('c'), {{ navigate: mockNavigate }});
    assert.strictEqual(currentUrl, '/coding-practice', 'g c should navigate to /coding-practice');

    // Typing in an input must be ignored
    currentUrl = 'unchanged';
    const inputTarget = {{ tagName: 'INPUT', type: 'text', getAttribute: () => null }};
    assert.strictEqual(isTypingElement(inputTarget), true);
    handleKeydownEvent(fakeEvent('g', {{ target: inputTarget }}), {{ navigate: mockNavigate }});
    handleKeydownEvent(fakeEvent('d', {{ target: inputTarget }}), {{ navigate: mockNavigate }});
    assert.strictEqual(currentUrl, 'unchanged', 'Typing in input must be ignored');

    // Ctrl+Enter must be ignored
    prevented = false;
    handleKeydownEvent(fakeEvent('Enter', {{ ctrlKey: true }}), {{ navigate: mockNavigate }});
    assert.strictEqual(prevented, false, 'Ctrl+Enter must not be prevented');

    console.log('JS SIMULATION ALL PASSED');
    """

    try:
        res = subprocess.run(
            [node_bin, "--input-type=module", "-e", test_script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except OSError as exc:
        pytest.skip(f"Subprocess execution not permitted in current sandbox: {exc}")

    assert res.returncode == 0, f"Node test failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    assert "JS SIMULATION ALL PASSED" in res.stdout
