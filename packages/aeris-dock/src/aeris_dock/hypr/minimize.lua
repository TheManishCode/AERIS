-- Minimize / restore for Hyprland
-- =============================================================================
-- Hyprland has no minimize. A client that calls xdg_toplevel.set_minimized is
-- ignored outright: verified on 0.56.2 by driving a GTK4 window through
-- Gtk.Window.minimize() while tailing .socket2.sock -- the compositor emits no
-- event at all, so the titlebar minimize button in CSD apps (Chromium, Electron)
-- cannot be made to work from config. Minimizing has to be driven by a keybind
-- or by an external client issuing a dispatch.
--
-- The mechanism is the one from the wiki: park the window on a special
-- workspace. What the wiki snippet does NOT do, and this does:
--
--   * handles more than one window (the wiki version is one keybind per window)
--   * remembers which workspace each window came from, and returns it there --
--     the wiki version dumps everything onto whatever workspace is active
--   * survives `hyprctl reload`, because the state lives in window tags
--     (compositor state) and not in a Lua table (config state, wiped on reload)
--   * restores fullscreen/pinned state instead of silently dropping it
--   * is readable by external tools: `hyprctl clients -j` exposes .tags, which
--     is how the AERIS taskbar lists and targets individual windows
--
-- State model. Two tags per minimized window:
--   "minimized"                -- the flag, so queries are a single exact match
--   "minstate:SEQ:WS:FS:PIN"   -- the payload needed to put it back
-- SEQ is a monotonic counter giving LIFO restore order; WS is the origin
-- workspace id; FS is the fullscreen mode (0/1/2); PIN is 0/1.
--
-- Complexity: every operation is O(n) in the window count with n in the tens.
-- =============================================================================

local M = {}

local SCRATCH = "special:minimized"
local FLAG = "minimized"
local PREFIX = "minstate:"

--- Highest SEQ seen this session. Rebuilt from tags on first use so that a
--- config reload does not restart numbering and invert the restore order.
local seq = nil

local function notify(summary, body)
    hl.exec_cmd(string.format(
        "notify-send %q %q -a Hyprland -t 2000", summary, body or ""))
end

--- Tags come back as a table for a window and may be absent on some paths.
local function tags_of(win)
    local t = win and win.tags
    if type(t) == "table" then return t end
    if type(t) == "string" then return { t } end
    return {}
end

local function has_tag(win, name)
    for _, t in ipairs(tags_of(win)) do
        if t == name then return true end
    end
    return false
end

--- The "minstate:" tag's four fields, or nil when the window has none.
local function state_of(win)
    for _, t in ipairs(tags_of(win)) do
        local s, ws, fs, pin = t:match("^minstate:(%d+):(-?%d+):(%d+):(%d+)$")
        if s then
            return {
                seq = tonumber(s),
                workspace = tonumber(ws),
                fullscreen = tonumber(fs),
                pinned = pin == "1",
            }
        end
    end
    return nil
end

--- Every minimized window, newest first.
---
--- Deliberately filters in Lua over the full window list rather than trusting
--- `get_windows({ tag = ... })` to be an exact match -- Hyprland's other
--- matchers are regex, and a window tagged "minimized_something" by an
--- unrelated tool must not be swept up and moved.
local function minimized_windows()
    local out = {}
    for _, win in ipairs(hl.get_windows({}) or {}) do
        local st = has_tag(win, FLAG) and state_of(win)
        if st then
            out[#out + 1] = { win = win, state = st }
        end
    end
    table.sort(out, function(a, b) return a.state.seq > b.state.seq end)
    return out
end

local function next_seq()
    if seq == nil then
        seq = 0
        for _, entry in ipairs(minimized_windows()) do
            if entry.state.seq > seq then seq = entry.state.seq end
        end
    end
    seq = seq + 1
    return seq
end

local function addr(win)
    return "address:" .. win.address
end

--- HL.Window.fullscreen is 0 none / 1 maximized / 2 fullscreen.
---
--- The mode has to be named on the way *out* as well as in: `action = "unset"`
--- with no mode only clears mode 2, and returns "ok" while doing nothing to a
--- maximized window. Verified on 0.56.2.
local FS_MODE = { [1] = "maximized", [2] = "fullscreen" }

--- Send the focused window (or a given one) to the minimize drawer.
function M.minimize(win)
    win = win or hl.get_active_window()
    if not win then
        notify("Nothing to minimize", "No focused window")
        return false
    end
    if has_tag(win, FLAG) then
        return false -- already there; re-tagging would lose the origin
    end

    local ws = win.workspace
    if not ws then return false end
    -- A window already parked on a special workspace (the scratchpad, or this
    -- drawer) has no meaningful origin to return to.
    if ws.id < 0 then
        notify("Can't minimize", "Window is on a special workspace")
        return false
    end

    local fullscreen = win.fullscreen or 0
    local pinned = win.pinned and 1 or 0

    -- Clear fullscreen before parking: a fullscreen window dragged onto a
    -- special workspace makes that workspace fullscreen, and revealing the
    -- drawer then blanks the monitor.
    if FS_MODE[fullscreen] then
        hl.dispatch(hl.dsp.window.fullscreen({
            window = addr(win), mode = FS_MODE[fullscreen], action = "unset",
        }))
    end
    if pinned == 1 then
        hl.dispatch(hl.dsp.window.pin({ window = addr(win) }))
    end

    hl.dispatch(hl.dsp.window.tag({ tag = FLAG, window = addr(win) }))
    hl.dispatch(hl.dsp.window.tag({
        tag = string.format("%s%d:%d:%d:%d", PREFIX, next_seq(), ws.id, fullscreen, pinned),
        window = addr(win),
    }))
    hl.dispatch(hl.dsp.window.move({
        workspace = SCRATCH, window = addr(win), follow = false,
    }))
    return true
end

--- Put one window back where it came from and focus it.
function M.restore(win, state)
    if not win then return false end
    state = state or state_of(win)
    if not state then return false end

    -- Move before untagging. If the move fails the window stays labelled and
    -- the taskbar can retry; untagging first would strand it in the drawer
    -- with no record of where it belongs.
    hl.dispatch(hl.dsp.window.move({
        workspace = tostring(state.workspace), window = addr(win), follow = false,
    }))
    hl.dispatch(hl.dsp.window.clear_tags({ window = addr(win) }))
    if state.pinned then
        hl.dispatch(hl.dsp.window.pin({ window = addr(win) }))
    end
    if FS_MODE[state.fullscreen] then
        hl.dispatch(hl.dsp.window.fullscreen({
            window = addr(win), mode = FS_MODE[state.fullscreen], action = "set",
        }))
    end
    -- Follow the window to its own workspace rather than yanking it to the
    -- current one: that is what makes this a restore and not a "fetch".
    hl.dispatch(hl.dsp.focus({ workspace = tostring(state.workspace) }))
    hl.dispatch(hl.dsp.focus({ window = addr(win) }))
    return true
end

--- Restore the most recently minimized window.
function M.restore_last()
    local list = minimized_windows()
    if #list == 0 then
        notify("Nothing minimized", "")
        return false
    end
    return M.restore(list[1].win, list[1].state)
end

--- Minimize the focused window, or bring the last one back if the focused
--- window is itself the only thing worth toggling. Bound to a single key for
--- the common "stash this, then get it back" rhythm.
function M.toggle()
    local win = hl.get_active_window()
    if win and not has_tag(win, FLAG) and M.minimize(win) then
        return true
    end
    return M.restore_last()
end

--- Restore everything, newest last so focus lands on the oldest-hidden window.
function M.restore_all()
    local list = minimized_windows()
    if #list == 0 then
        notify("Nothing minimized", "")
        return false
    end
    for i = #list, 1, -1 do
        M.restore(list[i].win, list[i].state)
    end
    return true
end

function M.count()
    return #minimized_windows()
end

--- "Show desktop" (Win+D): clear the active workspace, or put it back.
---
--- Scoped to the active workspace, which is the useful reading of the gesture
--- in a tiling WM. Restore is not a separate mode: if anything from *this*
--- workspace is already in the drawer, that is what the key undoes.
function M.toggle_show_desktop()
    local ws = hl.get_active_workspace()
    if not ws then return false end

    local mine = {}
    for _, entry in ipairs(minimized_windows()) do
        if entry.state.workspace == ws.id then
            mine[#mine + 1] = entry
        end
    end

    if #mine > 0 then
        for i = #mine, 1, -1 do
            M.restore(mine[i].win, mine[i].state)
        end
        return true
    end

    local n = 0
    -- Snapshot first: minimizing mutates the workspace's window list, and
    -- iterating it while it changes under us skips windows.
    local windows = ws:get_windows() or {}
    for _, win in ipairs(windows) do
        if win.mapped and M.minimize(win) then n = n + 1 end
    end
    if n == 0 then
        notify("Show desktop", "Nothing to minimize")
        return false
    end
    return true
end

--- Restore by address, for external callers:
---   hyprctl dispatch "hl.dispatch(function() Minimize.restore_address('0x...') end)"
--- Used by the AERIS taskbar to target one specific window.
function M.restore_address(address)
    for _, entry in ipairs(minimized_windows()) do
        if entry.win.address == address then
            return M.restore(entry.win, entry.state)
        end
    end
    return false
end

--- Minimize by address, so an external taskbar can stash a window it did not
--- have focus on.
function M.minimize_address(address)
    local win = hl.get_window("address:" .. address)
    if not win then return false end
    return M.minimize(win)
end

-- The drawer should not look like a normal workspace when it is revealed.
hl.workspace_rule({ workspace = SCRATCH, gaps_out = 30, border_size = 2 })

-- Exposed globally so `hyprctl dispatch` from an external process can reach it.
Minimize = M
return M
