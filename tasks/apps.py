from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tasks'

    def ready(self):
        import sys
        import os

        # Skip during management commands that don't serve requests
        if any(arg in sys.argv for arg in ['makemigrations', 'migrate', 'collectstatic', 'check']):
            return

        # In dev (runserver), Django spawns a reloader process and a main process.
        # RUN_MAIN='true' is set on the MAIN worker process — that's where we start.
        # On Gunicorn/production there is no reloader, so RUN_MAIN is unset — start there too.
        is_runserver = 'runserver' in sys.argv
        run_main     = os.environ.get('RUN_MAIN') == 'true'

        if is_runserver and not run_main:
            # This is the reloader watcher process — skip
            return

        from .tasks import repair_live_database
        repair_live_database()

        # Seed required status options so start/complete always work
        from .models import statusoption
        for name in ['Pending', 'In Progress', 'Completed', 'Overdue', 'Awaiting Approval']:
            statusoption.objects.get_or_create(name=name)

        from .background_worker import start_automation_engine
        start_automation_engine()
