import logging
from datetime import datetime, timedelta
from .models import (
    app_user, task_management, assignment, notification, statusoption, forum_entry
)

logger = logging.getLogger(__name__)


def _get_admin_id():
    admin = app_user.objects.filter(role__iexact='admin', deleted=False).first()
    return admin.id if admin else 1


def _notify(user_id, title, message):
    """Safe notification helper — never raises."""
    try:
        notification.objects.create(user_id=user_id, title=title, message=message)
    except Exception as e:
        logger.error(f"[NOTIFY] Failed to create notification: {e}")


def monitor_assignments_lifecycle():
    """
    5-minute slot: Detects unstarted tasks, newly overdue deadlines,
    and sends a 5-minute deadline warning to employees.
    """
    try:
        from django.utils import timezone
        now = timezone.now()
        clock_time = timezone.localtime(now).strftime("%I:%M %p")
        admin_id = _get_admin_id()

        # ── 1. NOT STARTED alert (admin) ────────────────────────────────────
        unstarted = assignment.objects.filter(
            status__name__iexact='Pending',
            start_date__isnull=True,
            notified_start=False,
            deleted=False
        ).select_related('task', 'assigned_to')

        if unstarted.exists():
            count = unstarted.count()
            details = ", ".join(
                [f"{a.task.title} ({a.assigned_to.name})" for a in unstarted[:5]]
            )
            if count > 5:
                details += "..."
            _notify(admin_id, "TASK ALERT",
                    f"⚠ {count} task(s) NOT STARTED (as of {clock_time}): {details}")
            unstarted.update(notified_start=True)

        # ── 2. Newly OVERDUE (admin + employee) ─────────────────────────────
        status_overdue, _ = statusoption.objects.get_or_create(name='Overdue')
        overdue_qs = assignment.objects.filter(
            deleted=False,
            deadline__lt=now,
            notified_overdue=False
        ).exclude(status__name__iexact='Completed').select_related('task', 'assigned_to')

        if overdue_qs.exists():
            count = overdue_qs.count()
            details = ", ".join(
                [f"{a.task.title} ({a.assigned_to.name})" for a in overdue_qs[:5]]
            )
            if count > 5:
                details += "..."
            _notify(admin_id, "OVERDUE ALERT",
                    f"🚨 {count} task(s) OVERDUE as of {clock_time}: {details}")

            # Notify each employee individually
            for a in overdue_qs:
                _notify(a.assigned_to.id, "TASK OVERDUE",
                        f"🚨 Your task '{a.task.title}' is now OVERDUE. Please act immediately!")

            overdue_qs.update(status=status_overdue, notified_overdue=True)

        # ── 3. 5-MINUTE DEADLINE WARNING (employee) ─────────────────────────
        # Find assignments whose deadline is within the next 5–10 minutes
        # and haven't been warned yet (use notified_start as a proxy flag
        # since we add a dedicated field below — for now use a title check).
        warn_from = now
        warn_to   = now + timedelta(minutes=10)

        upcoming = assignment.objects.filter(
            deleted=False,
            deadline__gte=warn_from,
            deadline__lte=warn_to,
        ).exclude(
            status__name__iexact='Completed'
        ).exclude(
            status__name__iexact='Overdue'
        ).select_related('task', 'assigned_to')

        for a in upcoming:
            # Avoid duplicate warnings: check if we already sent one in the last 15 min
            already_warned = notification.objects.filter(
                user_id=a.assigned_to.id,
                title="DEADLINE WARNING",
                message__contains=a.task.title,
            ).filter(
                created_at__gte=now - timedelta(minutes=15)
            ).exists()

            if not already_warned:
                mins_left = max(0, int((a.deadline - now).total_seconds() // 60))
                _notify(a.assigned_to.id, "DEADLINE WARNING",
                        f"⏰ Deadline in ~{mins_left} min: '{a.task.title}'. Complete it now!")
                # Also alert admin
                _notify(admin_id, "DEADLINE APPROACHING",
                        f"⏰ {a.assigned_to.name}'s task '{a.task.title}' deadline in ~{mins_left} min.")

    except Exception as e:
        logger.error(f"[LIFECYCLE] Error: {e}", exc_info=True)


def generate_admin_summary():
    """10-minute slot: Workload summary for admin."""
    try:
        from django.utils import timezone
        now = timezone.now()
        clock_time = timezone.localtime(now).strftime("%I:%M %p")
        admin_id = _get_admin_id()

        pending  = assignment.objects.filter(status__name__iexact='Pending',     deleted=False).count()
        active   = assignment.objects.filter(status__name__iexact='In Progress', deleted=False).count()
        overdue  = assignment.objects.filter(status__name__iexact='Overdue',     deleted=False).count()
        done_today = assignment.objects.filter(
            status__name__iexact='Completed',
            end_date__date=timezone.localtime(now).date(),
            deleted=False
        ).count()

        _notify(admin_id, "WORKLOAD SUMMARY",
                f"📊 Summary at {clock_time} — "
                f"Pending: {pending} | Active: {active} | "
                f"Overdue: {overdue} | Completed today: {done_today}")

    except Exception as e:
        logger.error(f"[SUMMARY] Error: {e}", exc_info=True)


def trigger_overdue_recurring_nag():
    """10-minute slot: Remind employees with overdue tasks."""
    try:
        from django.utils import timezone
        clock_time = timezone.localtime(timezone.now()).strftime("%I:%M %p")
        admin_id = _get_admin_id()

        overdue_assignments = assignment.objects.filter(
            status__name__iexact='Overdue',
            deleted=False
        ).select_related('assigned_to', 'task')

        if not overdue_assignments.exists():
            return

        # Group by employee
        user_tasks: dict = {}
        for a in overdue_assignments:
            uid = a.assigned_to.id
            user_tasks.setdefault(uid, {'user': a.assigned_to, 'titles': []})
            user_tasks[uid]['titles'].append(a.task.title)

        for uid, data in user_tasks.items():
            count = len(data['titles'])
            titles = ", ".join(data['titles'][:3])
            if count > 3:
                titles += "..."
            _notify(uid, "OVERDUE REMINDER",
                    f"⚠ {count} task(s) still OVERDUE at {clock_time}: {titles}. "
                    f"Please complete them immediately!")

        total = overdue_assignments.count()
        _notify(admin_id, "OVERDUE NAG SUMMARY",
                f"🚨 Nag sent at {clock_time}: {len(user_tasks)} employee(s) "
                f"have {total} overdue task(s) unresolved.")

    except Exception as e:
        logger.error(f"[NAG] Error: {e}", exc_info=True)


def cleanup_expired_otps():
    """Hourly: Remove OTPs older than 5 minutes."""
    try:
        from .models import otp_entry
        from django.utils import timezone
        expiry = timezone.now() - timedelta(minutes=5)
        deleted, _ = otp_entry.objects.filter(created_at__lt=expiry).delete()
        if deleted:
            logger.info(f"[CLEANUP] Removed {deleted} expired OTPs.")
    except Exception as e:
        logger.error(f"[CLEANUP-OTP] Error: {e}", exc_info=True)


def cleanup_old_forum_messages():
    """Hourly: Soft-delete forum messages older than 24 hours."""
    try:
        from django.utils import timezone
        expiry = timezone.now() - timedelta(hours=24)
        deleted, _ = forum_entry.objects.filter(
            dtm_created__lt=expiry, deleted=False
        ).update(deleted=True), None
        logger.info(f"[CLEANUP] Archived old forum messages.")
    except Exception as e:
        logger.error(f"[CLEANUP-FORUM] Error: {e}", exc_info=True)


def repair_live_database():
    """Startup: Fix legacy date strings and remove stale heartbeats."""
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            for col in ('start_date', 'deadline', 'end_date'):
                cursor.execute(
                    f"UPDATE assignment SET {col} = {col} || ' 00:00:00' "
                    f"WHERE {col} IS NOT NULL "
                    f"AND length({col}) = 10 "
                    f"AND {col} NOT LIKE '%:%'"
                )
        notification.objects.filter(title="SYS_HEARTBEAT").delete()
        logger.info("[REPAIR] Database normalisation complete.")
    except Exception as e:
        logger.error(f"[REPAIR] Error: {e}", exc_info=True)
