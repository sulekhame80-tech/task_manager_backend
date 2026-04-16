import threading
import time
import logging
from datetime import datetime, timedelta
from .tasks import (
    monitor_assignments_lifecycle, generate_admin_summary, 
    cleanup_expired_otps, trigger_overdue_recurring_nag,
    cleanup_old_forum_messages
)

logger = logging.getLogger(__name__)

def automation_loop():
    """ The heartbeat of the 'Always Active' Backend Engine. """
    logger.info("[ENGINE] Starting Background Automation Loop...")
    
    # 🚀 1. Startup Delay
    time.sleep(10)
    
    import random
    last_run_min = -1

    while True:
        try:
            # 🚀 0. Wider Jitter (Staggers multiple workers)
            # Increased to 15s to reduce concurrency collisions on SQLite
            time.sleep(random.random() * 15)

            now = datetime.now()
            current_min = now.minute

            # 🛠️ 1. Once-per-minute execution check
            if current_min == last_run_min:
                time.sleep(5)
                continue

            # 🛠️ 2. PRECISION GUARD
            # We generate a unique ID for this specific minute and slot.
            day_str = now.strftime("%Y-%m-%d")
            # All workers target the SAME Slot-ID for a given minute.
            slot_id = f"{day_str}_{now.hour:02d}:{current_min:02d}"

            logger.info(f"[ENGINE] Evaluating slot: {slot_id}")

            # 📊 3. Exclusive Slots
            # Multiples of 10 (:00, :10, :20...) -> SUMMARY + NAG
            if current_min % 10 == 0:
                logger.info(f"[ENGINE] Processing Slot {slot_id}: Summary & Nag...")
                generate_admin_summary(slot_id=slot_id)
                trigger_overdue_recurring_nag() # This handles its own logic inside
            
            # Multiples of 5 (BUT NOT 10) (:05, :15, :25...) -> PRIMARY OVERDUE
            elif current_min % 5 == 0:
                logger.info(f"[ENGINE] Processing Slot {slot_id}: Primary Overdue...")
                monitor_assignments_lifecycle(slot_id=slot_id)

            # 🧹 4. System Maintenance (Every hour at :01)
            if current_min == 1:
                logger.info("[ENGINE] Running hourly system maintenance...")
                cleanup_expired_otps()
                cleanup_old_forum_messages()

            last_run_min = current_min

        except Exception as e:
            logger.error(f"[ENGINE] Loop Error: {e}", exc_info=True)

        time.sleep(5)

def start_automation_engine():
    """ Main entry point to start the daemon thread. """
    thread = threading.Thread(target=automation_loop, daemon=True)
    thread.start()
    logger.info("[ENGINE] Daemon thread initialized.")
