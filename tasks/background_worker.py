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
    
    # 🚀 1. Startup Delay: Give the system time to finalize migrations and settlements
    logger.info("[ENGINE] Entering 10s startup cooldown...")
    time.sleep(10)
    
    last_summary = datetime.now() - timedelta(seconds=30) 
    last_nag = datetime.now()
    last_overdue = datetime.now()
    last_1m_maint = datetime.now()

    while True:
        try:
            now = datetime.now()

            # 🔄 1. Immediate Monitoring (Tasks and Status Lifecycle)
            # Detects "Task Started" etc. immediately (~45s)
            try:
                monitor_assignments_lifecycle()
            except Exception as e:
                # If tables don't exist yet, we just wait
                if "no such table" in str(e).lower():
                    logger.warning("[ENGINE] Database tables not ready yet. Retrying in 10s...")
                    time.sleep(10)
                    continue
                raise e

            # 📊 2. 10-Minute Admin Summary
            if now >= last_summary + timedelta(minutes=10):
                logger.info("[ENGINE] Generating 10-minute Admin Summary...")
                generate_admin_summary()
                last_summary = now

            # 🚨 3. 5-Minute Overdue Primary Check
            if now >= last_overdue + timedelta(minutes=5):
                logger.info("[ENGINE] Running 5-minute Primary Overdue Check...")
                monitor_assignments_lifecycle() # Re-confirming state
                trigger_overdue_recurring_nag() # <--- Also run nag here
                last_overdue = now
                last_nag = now # Synced

            # 🧹 4. One-Minute System Maintenance (OTP Cleanup)
            if now >= last_1m_maint + timedelta(minutes=1):
                logger.info("[ENGINE] Running 1-minute System Maintenance...")
                cleanup_expired_otps()
                cleanup_old_forum_messages() # Check for old chat messages
                last_1m_maint = now

        except Exception as e:
            logger.error(f"[ENGINE] Error in automation loop: {e}", exc_info=True)

        # 🐢 Throttled Sleep (Increased precision for 30s checks)
        time.sleep(2)

def start_automation_engine():
    """ Main entry point to start the daemon thread. """
    thread = threading.Thread(target=automation_loop, daemon=True)
    thread.start()
    logger.info("[ENGINE] Daemon thread initialized.")
