import os
import sys
import time
import shutil
import threading
import subprocess
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os, sys, shutil

def resource_path(rel_path):
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel_path)

def find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return p
    candidate = resource_path("ffmpeg.exe")
    return candidate if os.path.exists(candidate) else None

def find_ffprobe():
    p = shutil.which("ffprobe")
    if p:
        return p
    candidate = resource_path("ffprobe.exe")
    return candidate if os.path.exists(candidate) else None

SAFE_ARGS = [
    "-c:v", "libx264",
    "-profile:v", "baseline",
    "-level", "3.1",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "128k",
    "-movflags", "+faststart",
]

def have_ffmpeg():
    """Return path to ffmpeg if available, else None."""
    path = shutil.which("ffmpeg")
    return path

def run_ffprobe(input_file):
    """Return a short ffprobe output string or an error message."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return "ffprobe not found. Skipping detailed probe.\n"
    try:
        out = subprocess.check_output(
            [ffprobe, "-v", "error", "-show_entries", "format=format_name,format_long_name",
             "-show_streams", "-of", "default=noprint_wrappers=1", input_file],
            stderr=subprocess.STDOUT,
        )
        return out.decode(errors="replace")
    except subprocess.CalledProcessError as e:
        return f"ffprobe failed:\n{e.output.decode(errors='replace')}\n"

def build_fast_remux_cmd(src, dst):
    # Re-mux only and put moov atom at front
    return ["ffmpeg", "-y", "-i", src, "-c", "copy", "-movflags", "+faststart", dst]

def build_safe_encode_cmd(src, dst):
    return ["ffmpeg", "-y", "-i", src] + SAFE_ARGS + [dst]

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Meta WABA-safe Video Converter")
        self.geometry("820x560")
        self.minsize(820, 560)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.force_encode = tk.BooleanVar(value=False)

        self.create_widgets()

        self.proc = None
        self.log_queue = queue.Queue()
        self.poll_logs()

    def create_widgets(self):
        pad = 8

        # Input file
        frm_in = ttk.LabelFrame(self, text="1) Choose input video")
        frm_in.pack(fill="x", padx=pad, pady=(pad, 0))
        ent_in = ttk.Entry(frm_in, textvariable=self.input_path)
        ent_in.pack(side="left", fill="x", expand=True, padx=pad, pady=pad)
        ttk.Button(frm_in, text="Browse...", command=self.browse_input).pack(side="right", padx=pad, pady=pad)

        # Output file
        frm_out = ttk.LabelFrame(self, text="2) Choose output file")
        frm_out.pack(fill="x", padx=pad, pady=(pad, 0))
        ent_out = ttk.Entry(frm_out, textvariable=self.output_path)
        ent_out.pack(side="left", fill="x", expand=True, padx=pad, pady=pad)
        ttk.Button(frm_out, text="Save as...", command=self.browse_output).pack(side="right", padx=pad, pady=pad)

        # Options
        frm_opts = ttk.LabelFrame(self, text="Options")
        frm_opts.pack(fill="x", padx=pad, pady=(pad, 0))
        ttk.Checkbutton(frm_opts, text="Force clean re-encode (H.264 baseline + AAC + faststart)", variable=self.force_encode).pack(anchor="w", padx=pad, pady=(pad, 0))

        # Actions
        frm_actions = ttk.Frame(self)
        frm_actions.pack(fill="x", padx=pad, pady=(pad, 0))
        self.btn_convert = ttk.Button(frm_actions, text="Convert", command=self.on_convert)
        self.btn_convert.pack(side="left", padx=(pad, 4), pady=pad)

        self.btn_probe = ttk.Button(frm_actions, text="Probe input", command=self.on_probe)
        self.btn_probe.pack(side="left", padx=4, pady=pad)

        self.btn_stop = ttk.Button(frm_actions, text="Stop", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4, pady=pad)

        # Log box
        frm_log = ttk.LabelFrame(self, text="Verbose log")
        frm_log.pack(fill="both", expand=True, padx=pad, pady=pad)
        self.txt = tk.Text(frm_log, wrap="word")
        self.txt.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(frm_log, command=self.txt.yview)
        self.txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        # Initial tips
        self.log("Ready.\n- Pick an input video\n- Choose output file\n- Click Convert\n")
        self.log("Tip: if Meta flagged your video as application/octet-stream, try Force clean re-encode.\n\n")

    def log(self, msg):
        self.txt.insert("end", msg)
        self.txt.see("end")
        self.update_idletasks()

    def qlog(self, msg):
        self.log_queue.put(msg)

    def poll_logs(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log(msg)
        except queue.Empty:
            pass
        self.after(80, self.poll_logs)

    def browse_input(self):
        path = filedialog.askopenfilename(
            title="Select input video",
            filetypes=[("Video files", "*.mp4 *.mov *.m4v *.3gp *.3g2 *.mkv *.webm *.avi"), ("All files", "*.*")]
        )
        if path:
            self.input_path.set(path)
            # Suggest default output name
            base, _ = os.path.splitext(path)
            self.output_path.set(base + "_waba.mp4")

    def browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save output as",
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4")]
        )
        if path:
            self.output_path.set(path)

    def on_probe(self):
        src = self.input_path.get().strip()
        if not src:
            messagebox.showwarning("No input", "Please select an input video first.")
            return
        self.log(f"Probing file: {src}\n")
        info = run_ffprobe(src)
        self.log(info + "\n")

    def on_convert(self):
        src = self.input_path.get().strip()
        dst = self.output_path.get().strip()

        if not src:
            messagebox.showwarning("No input", "Please select an input video.")
            return
        if not os.path.exists(src):
            messagebox.showerror("Input not found", f"File does not exist:\n{src}")
            return
        if not dst:
            messagebox.showwarning("No output", "Please choose where to save the output file.")
            return

        ffm = have_ffmpeg()
        if not ffm:
            self.log("ffmpeg not found on PATH.\n")
            self.log("Install ffmpeg and restart this app.\n")
            self.log("- Windows: https://www.gyan.dev/ffmpeg/builds/ (add bin folder to PATH)\n")
            self.log("- macOS: brew install ffmpeg\n")
            self.log("- Linux: sudo apt install ffmpeg or your distro equivalent\n\n")
            messagebox.showerror("ffmpeg missing", "ffmpeg is not installed or not on PATH.")
            return

        self.btn_convert.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.txt.delete("1.0", "end")

        force = self.force_encode.get()
        if force:
            cmd = build_safe_encode_cmd(src, dst)
            mode = "Clean re-encode to safe profile"
        else:
            cmd = build_fast_remux_cmd(src, dst)
            mode = "Fast re-mux to MP4 with +faststart"

        self.log(f"Mode: {mode}\n")
        self.log(f"Using ffmpeg: {ffm}\n")
        self.log("Command:\n" + " ".join(cmd) + "\n\n")

        # Run in a thread, stream stderr for progress
        t = threading.Thread(target=self.run_cmd_streaming, args=(cmd,))
        t.daemon = True
        t.start()

    def on_stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.qlog("\nRequested stop. Waiting for ffmpeg to exit...\n")
            except Exception as e:
                self.qlog(f"\nFailed to terminate: {e}\n")

    def run_cmd_streaming(self, cmd):
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                universal_newlines=True
            )
            # ffmpeg prints to stderr for progress
            for line in self.proc.stderr:
                self.qlog(line)

            rc = self.proc.wait()
            if rc == 0:
                self.qlog("\n✅ Done. Output saved.\n")
                out = self.output_path.get().strip()
                try:
                    size_mb = os.path.getsize(out) / (1024 * 1024)
                    self.qlog(f"Output size: {size_mb:.2f} MB\n")
                except Exception:
                    pass
                self.qlog("\nIf Meta still rejects the file:\n")
                self.qlog("- Tick Force clean re-encode and run again\n")
                self.qlog("- Ensure you upload with Content-Type: video/mp4\n")
            else:
                self.qlog(f"\n❌ ffmpeg exited with code {rc}\n")
        except FileNotFoundError:
            self.qlog("ffmpeg not found. Please install ffmpeg and try again.\n")
        except Exception as e:
            self.qlog(f"\nError: {e}\n")
        finally:
            self.btn_convert.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.proc = None

if __name__ == "__main__":
    app = App()
    app.mainloop()
