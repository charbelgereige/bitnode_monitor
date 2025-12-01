#!/usr/bin/env python3
import time
import statistics


class SpeedTracker:
    """
    Tracks Fulcrum indexing speed (blocks/sec) with an EMA + std-dev.
    """
    def __init__(self, window: int = 50):
        self.window = window
        self.samples = []   # recent speeds (blocks/sec)
        self.last_height = None
        self.last_time = None

    def update(self, height: int):
        now = time.time()
        if self.last_height is not None and height is not None:
            dh = height - self.last_height
            dt = now - self.last_time if self.last_time is not None else 0
            if dt > 0 and dh >= 0:
                speed = dh / dt
                self.samples.append(speed)
                if len(self.samples) > self.window:
                    self.samples = self.samples[-self.window:]
        self.last_height = height
        self.last_time = now

    def get_stats(self):
        """
        Returns (ema_speed, stdev) or (None, None) if no data.
        """
        if not self.samples:
            return None, None
        alpha = 0.2
        ema = self.samples[0]
        for s in self.samples[1:]:
            ema = alpha * s + (1 - alpha) * ema
        stdev = statistics.pstdev(self.samples) if len(self.samples) > 1 else 0.0
        return ema, stdev
