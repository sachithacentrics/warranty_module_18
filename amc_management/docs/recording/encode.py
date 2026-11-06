"""Encode the screencast frames to MP4 (H.264), cap static gaps, remap chapters.
Usage: encode.py <video_dir> <out.mp4> <out_chapters.json> <out_poster.jpg>"""
import json
import os
import shutil
import subprocess
import sys

import imageio_ffmpeg

DIR, OUT, CHAP_OUT, POSTER = sys.argv[1:5]
CAP = 3.0  # longest still image (server-side steps produce no frames)
frames = json.load(open(os.path.join(DIR, 'frames.json')))
chapters = json.load(open(os.path.join(DIR, 'chapters.json')))
t0 = frames[0]['t']

durations, video_t, acc = [], [], 0.0
for i, f in enumerate(frames):
    nxt = frames[i + 1]['t'] if i + 1 < len(frames) else f['t'] + 2.0
    d = min(max(nxt - f['t'], 0.02), CAP)
    video_t.append(acc)
    durations.append(d)
    acc += d


def to_video(abs_t):
    for i in range(len(frames) - 1, -1, -1):
        if frames[i]['t'] <= abs_t:
            return round(video_t[i] + min(abs_t - frames[i]['t'], durations[i]), 1)
    return 0.0


mapped = [{'title': c['title'], 'start': to_video(t0 + c['start'])} for c in chapters]
mapped[0]['start'] = 0.0
json.dump({'duration': round(acc, 1), 'chapters': mapped}, open(CHAP_OUT, 'w'), indent=1)

lst = os.path.join(DIR, 'concat.txt')
with open(lst, 'w') as handle:
    for f, d in zip(frames, durations):
        handle.write("file '%s'\nduration %.3f\n" % (os.path.join(DIR, 'frames', f['file']).replace('\\', '/'), d))
    handle.write("file '%s'\n" % os.path.join(DIR, 'frames', frames[-1]['file']).replace('\\', '/'))
ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst,
       '-vf', 'fps=25,scale=1440:900:flags=lanczos,format=yuv420p', '-c:v', 'libx264',
       '-preset', 'slow', '-crf', '24', '-tune', 'stillimage', '-movflags', '+faststart', OUT]
subprocess.run(cmd, check=True)
shutil.copy(os.path.join(DIR, 'frames', frames[min(40, len(frames) - 1)]['file']), POSTER)
print('VIDEO', OUT, round(os.path.getsize(OUT) / 1e6, 1), 'MB', 'duration', round(acc, 1), 's')
for c in mapped:
    print('%6.1f  %s' % (c['start'], c['title']))
