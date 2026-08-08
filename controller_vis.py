class PlaybackController:
    """Controls playback of a single track and handles playback events."""
    def __init__(self, session, visualizer_factory):
        self.session, self.visualizer_factory, self.vis_thread = session, visualizer_factory, None

    def start(self, track, visual_on, has_renderer):
        self.track, self.has_renderer, self.visual_on = track, has_renderer, visual_on
        self.process = play_track(track); self.stop_event = threading.Event(); self.action_queue = py_queue.Queue()
        self.listener = threading.Thread(target=input_reader, args=(self.stop_event, self.action_queue, has_renderer), daemon=True); self.listener.start()
        self._ensure_vis()

    def _ensure_vis(self):
        if self.visual_on.get():
            if self.vis_thread is None or not self.vis_thread.is_alive():
                self.vis_thread = threading.Thread(target=run_visualizer, args=(self.session, self.visual_on), daemon=True); self.vis_thread.start()
        else: self.stop_vis()

    def stop_vis(self):
        if self.vis_thread: self.vis_thread.join(timeout=1)
        self.vis_thread = None

    def run_until_event(self):
        while self.process.poll() is None:
            try:
                if self.has_renderer and msvcrt:
                    if msvcrt.kbhit(): cmd = read_key_msvcrt()
                    else: cmd = None
                else: cmd = self.action_queue.get_nowait()
                if cmd:
                    act = action_for(cmd)
                    if act: return act
            except (py_queue.Empty, Exception): pass
            time.sleep(0.1)
        return "finished"

    def cleanup(self):
        self.stop_event.set(); kill_playback(self.process); time.sleep(0.1); self.stop_vis()

def get_ascii_frame(rows, cols, elapsed):
    frame = []
    for r in range(rows):
        line = []
        for c in range(cols):
            val = math.sin(r * 0.1 + elapsed) + math.cos(c * 0.1 + elapsed)
            line.append('@' if val > 1.2 else '#' if val > 0.6 else '*' if val > 0 else ' ')
        frame.append(''.join(line))
    return frame

def run_visualizer(session, visual_on):
    cols, rows = get_size(); elapsed = 0; sys.stdout.write(CLEAR)
    while visual_on.get():
        frame = get_ascii_frame(rows, cols, elapsed)
        sys.stdout.write('\033[H')
        print('\n'.join(frame))
        elapsed += 0.1; time.sleep(0.05)
    sys.stdout.write(CLEAR)
