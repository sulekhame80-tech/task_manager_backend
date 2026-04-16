from rest_framework import serializers
from .models import app_user, task_management, assignment, statusoption, priorityoption, notification, forum_entry

class UserSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='id', read_only=True)
    class Meta:
        model = app_user
        fields = ['id', 'user_id', 'name', 'email', 'role', 'phone', 'status', 'profile_image']

class TaskTemplateSerializer(serializers.ModelSerializer):
    priority = serializers.CharField(source='priority.name', read_only=True)
    
    class Meta:
        model = task_management
        fields = ['id', 'title', 'description', 'priority', 'dtm_created']

class AssignmentSerializer(serializers.ModelSerializer):
    task_title = serializers.CharField(source='task.title', read_only=True)
    task_desc = serializers.CharField(source='task.description', read_only=True)
    user_name = serializers.CharField(source='assigned_to.name', read_only=True)
    
    # Map to names as expected by frontend
    priority = serializers.CharField(source='task.priority.name', read_only=True)
    status = serializers.CharField(source='status.name', read_only=True)
    
    # Critical for Frontend ID mapping
    task_id = serializers.IntegerField(source='task.id', read_only=True)
    emp_id = serializers.IntegerField(source='assigned_to.id', read_only=True)
    user_id = serializers.IntegerField(source='assigned_to.id', read_only=True)

    class Meta:
        model = assignment
        fields = [
            'id', 'task', 'task_id', 'assigned_to', 'emp_id', 'user_id', 'status', 
            'task_title', 'task_desc', 'user_name', 
            'priority', 'status',
            'start_date', 'deadline', 'end_date', 'comments'
        ]

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = notification
        fields = ['id', 'user', 'title', 'message', 'status', 'created_at']

class ForumEntrySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.name', read_only=True)
    
    class Meta:
        model = forum_entry
        fields = ['id', 'user', 'user_name', 'message', 'reply', 'status', 'sender_role', 'is_read', 'dtm_created']
