import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── In-memory slot lock (safe: single daemon thread) ───────────────────────
# Stores "YYYY-MM-DD_HH:MM" strings for slots already executed this session.
_executed_slots: set = set()

def automation_loop():
    """The heartbeat of the Always-Active Backend Engine."""
    logger.info("[ENGINE] Starting Background Automation Loop...")

    # Startup delay — let Django finish initialising
    time.sleep(10)

    while True:
        try:
            from django.utils import timezone
            now = timezone.localtime(timezone.now())  # IST-aware
            current_min = now.minute

            day_str = now.strftime("%Y-%m-%d")
            slot_id  = f"{day_str}_{now.hour:02d}:{current_min:02d}"

            if slot_id not in _executed_slots:
                logger.info(f"[ENGINE] Executing slot: {slot_id}")

                # ── Every 10 minutes (:00, :10, :20 …) ─────────────────────
                if current_min % 10 == 0:
                    logger.info(f"[ENGINE] 10-min slot → Summary + Overdue Nag")
                    from .tasks import generate_admin_summary, trigger_overdue_recurring_nag
                    generate_admin_summary()
                    trigger_overdue_recurring_nag()

                # ── Every 5 minutes (but NOT 10) (:05, :15, :25 …) ─────────
                elif current_min % 5 == 0:
                    logger.info(f"[ENGINE] 5-min slot → Lifecycle Monitor")
                    from .tasks import monitor_assignments_lifecycle
                    monitor_assignments_lifecycle()

                # ── Hourly maintenance at :01 ────────────────────────────────
                if current_min == 1:
                    logger.info("[ENGINE] Hourly maintenance...")
                    from .tasks import cleanup_expired_otps, cleanup_old_forum_messages
                    cleanup_expired_otps()
                    cleanup_old_forum_messages()

                _executed_slots.add(slot_id)

                # Prune old slots to prevent unbounded memory growth
                if len(_executed_slots) > 500:
                    oldest = sorted(_executed_slots)[:250]
                    for s in oldest:
                        _executed_slots.discard(s)

        except Exception as e:
            logger.error(f"[ENGINE] Loop Error: {e}", exc_info=True)

        time.sleep(15)  # Check every 15 seconds


def start_automation_engine():
    """Start the background daemon thread."""
    thread = threading.Thread(target=automation_loop, daemon=True)
    thread.start()
    logger.info("[ENGINE] Daemon thread started.")
