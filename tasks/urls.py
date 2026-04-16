from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_user),
    path('master-data/', views.get_master_data),
    path('master/update/', views.update_master_data),
    
    path('employees/', views.get_employees),
    path('employees/create/', views.create_employee),
    path('employees/update/', views.update_employee),
    path('employees/delete/', views.delete_employee),

    # TASK LIBRARY
    path('library-all/', views.get_library_all),
    path('tasks/create/', views.create_task_template),
    path('tasks/update/', views.update_task_template),
    path('tasks/delete/', views.delete_task_template),

    # ASSIGNMENTS
    path('assignments/', views.manage_assignments),
    path('assignments/update/', views.update_assignment),
    path('assignments/delete/', views.delete_assignment),

    # STATS
    path('stats/', views.get_stats),

    # NOTIFICATIONS
    path('notifications/', views.get_notifications),
    path('notifications/read/', views.mark_notif_read),
    path('notifications/delete/', views.delete_notification),
    path('notifications/mark-all-read/', views.mark_all_notifs_read),
    path('notifications/clear/', views.clear_all_notifications),
    path('notifications/create/', views.create_notification),

    # FORUM
    path('forum/', views.get_forum_entries),
    path('forum/create/', views.create_forum_entry),
    path('forum/reply/', views.reply_forum_entry),
    path('forum/delete/', views.delete_forum_entry),
    path('forum/chat-users/', views.get_chat_users),
    path('forum/mark-read/', views.mark_forum_read),

    # TASK LIFECYCLE
    path('start-task/', views.start_task),
    path('complete-task/', views.complete_task),
    path('request-approval/', views.request_approval),
    path('assignments/update/', views.update_assignment),
    path('assignments/delete/', views.delete_assignment),
    path('master/update/', views.update_master_data),
    
    path('employee-status/', views.get_employee_status),
    path('pending-approvals/', views.get_pending_users),
    path('approve-user/', views.approve_user),
    
    path('reports/', views.get_reports),
    path('activity/', views.get_recent_activity),
    path('user-summary/', views.get_user_summary),
    path('check-overdue/', views.check_overdue),
    path('system-check/', views.run_system_check),
    path('pulse/', views.get_pulse),
]
