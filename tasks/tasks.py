import logging
from datetime import datetime
from .models import (
    app_user, task_management, assignment, notification, statusoption, forum_entry
)

logger = logging.getLogger(__name__)

def monitor_assignments_lifecycle():
    """
    Unified Monitoring Task (RUNS EVERY 10 SECONDS)
    Detects unstarted tasks and overdue deadlines, triggering popups ONCE.
    """
    logger.info("Starting lifecycle monitoring check...")
    try:
        # 1. NOT STARTED Alert
        unstarted = assignment.objects.filter(
            status__name='Pending', 
            start_date__isnull=True, 
            notified_start=False,
            deleted=False
        )
        for a in unstarted:
            notification.objects.create(user_id=1, title="TASK ALERT", message=f"⚠ Emp {a.assigned_to.id} has NOT STARTED Task {a.task.title}")
            a.notified_start = True
            a.save()
            logger.info(f"Alerted: Not Started for Assign ID {a.id}")

        # 2. OVERDUE Alert
        today = datetime.now().date()
        status_overdue, _ = statusoption.objects.get_or_create(name='Overdue')
        overdue_qs = assignment.objects.filter(
            deleted=False,
            deadline__lt=today,
            notified_overdue=False
        ).exclude(status__name='Completed')

        for a in overdue_qs:
            notification.objects.create(user_id=1, title="OVERDUE ALERT", message=f"🚨 OVERDUE: Task {a.task.title} delayed by User {a.assigned_to.name}")
            a.status = status_overdue
            a.notified_overdue = True
            a.save()
            logger.info(f"Alerted: Overdue for Assign ID {a.id}")
    except Exception as e:
        logger.error(f"Error in monitor_assignments_lifecycle: {e}")

def generate_admin_summary():
    """ 📊 Generates a 10-minute summary of all active workloads. """
    try:
        pending = assignment.objects.filter(status__name='Pending', deleted=False).count()
        active = assignment.objects.filter(status__name='In Progress', deleted=False).count()
        overdue = assignment.objects.filter(status__name='Overdue', deleted=False).count()
        
        # Stop notification if all critical counts are 0
        if (pending + active + overdue) == 0:
            logger.info("Admin Summary skipped: All work counters are zero.")
            return

        summary_msg = (
            f"📈 10-Min Summary: {active} In-Progress, "
            f"{pending} Pending, {overdue} Overdue."
        )

        # 🛡️ De-duplication: Check if identical summary was sent in last 60 seconds
        from django.utils import timezone
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(seconds=60)
        
        duplicate = notification.objects.filter(
            title="WORKLOAD SUMMARY",
            message=summary_msg,
            created_at__gte=cutoff
        ).exists()

        if duplicate:
            logger.info("Admin Summary duplicate suppressed.")
            return

        notification.objects.create(user_id=1, title="WORKLOAD SUMMARY", message=summary_msg)
        logger.info(f"Admin Summary Sent: {summary_msg}")
    except Exception as e:
        logger.error(f"Error generating admin summary: {e}")

def cleanup_expired_otps():
    """ 🧹 Periodically cleans up the OTP table. """
    try:
        from .models import otp_entry
        from django.utils import timezone
        from datetime import timedelta
        # Delete OTPs older than 5 minutes
        expiry = timezone.now() - timedelta(minutes=5)
        deleted_count, _ = otp_entry.objects.filter(created_at__lt=expiry).delete()
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired OTP entries from DB.")
    except Exception as e:
        logger.error(f"Error cleaning up OTPs: {e}")

def trigger_overdue_recurring_nag():
    """ 🔁 Recurring (10-min) nag for tasks that are ALREADY marked Overdue and not completed. """
    logger.info("Starting recurring overdue nag cycle...")
    try:
        overdue_tasks = assignment.objects.filter(status__name='Overdue', deleted=False)
        for a in overdue_tasks:
            # Notify Employee
            notification.objects.create(user=a.assigned_to, title="TASK OVERDUE", message=f"⚠ STICKY ALERT: Task {a.task.title} is OVERDUE. Please complete it immediately!")
            # Notify Admin
            notification.objects.create(user_id=1, title="NAG ALERT", message=f"🚨 NAG: User {a.assigned_to.name} is still ignoring Overdue Task {a.task.title}")
            
        if overdue_tasks.count() > 0:
            logger.info(f"Nagged {overdue_tasks.count()} overdue assignments.")
    except Exception as e:
        logger.error(f"Error in overdue nag: {e}")

def cleanup_old_forum_messages():
    """ 🧹 Periodically cleans up forum messages older than 24 hours. """
    try:
        from django.utils import timezone
        from datetime import timedelta
        # Delete messages older than 24 hours
        expiry = timezone.now() - timedelta(hours=24)
        deleted_count, _ = forum_entry.objects.filter(dtm_created__lt=expiry, deleted=False).delete()
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} forum messages older than 24 hours.")
    except Exception as e:
        logger.error(f"Error cleaning up forum messages: {e}")
