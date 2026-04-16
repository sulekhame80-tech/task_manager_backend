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
    
    last_run_min = -1

    while True:
        try:
            now = datetime.now()
            current_min = now.minute

            # 🛠️ 1. Once-per-minute execution check
            if current_min == last_run_min:
                time.sleep(5)
                continue

            # 🛠️ 2. Singleton Guard (Leader Election)
            # We use a hidden HEARTBEAT in system_log (NOT notifications) to ensure only one worker runs.
            from .models import app_user, system_log
            
            # Check if anyone already took this minute slot
            from django.utils import timezone
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(seconds=55)
            
            already_run = system_log.objects.filter(
                action__startswith="[SYS_HEARTBEAT]", 
                timestamp__gte=cutoff
            ).exists()

            if already_run:
                # Another worker is already handling this minute slot
                last_run_min = current_min
                continue

            # Attempt to claim the slot
            try:
                admin = app_user.objects.filter(role__iexact='admin').first()
                admin_id = admin.id if admin else 1
                # Save to system_log ONLY (Audit trail, no popups)
                system_log.objects.create(user_id=admin_id, action=f"[SYS_HEARTBEAT] Worker {current_min} active")
            except Exception:
                last_run_min = current_min
                continue

            logger.info(f"[ENGINE] Leading minute slot: {current_min}")

            # 📊 3. Exclusive Slots
            # Multiples of 10 (:00, :10, :20...) -> SUMMARY + NAG
            if current_min % 10 == 0:
                logger.info(f"[ENGINE] Slot {current_min}: Generating Summary & Nag...")
                generate_admin_summary()
                trigger_overdue_recurring_nag()
            
            # Multiples of 5 (BUT NOT 10) (:05, :15, :25...) -> PRIMARY OVERDUE
            elif current_min % 5 == 0:
                logger.info(f"[ENGINE] Slot {current_min}: Running Primary Overdue Check...")
                monitor_assignments_lifecycle()

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
