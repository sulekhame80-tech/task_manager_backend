from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import (
    app_user, task_management, assignment, notification, 
    forum_entry, system_log, otp_entry, statusoption, priorityoption
)
from datetime import datetime, date
from django.utils import timezone
import traceback
from django.db.models import Count, Q
from django.core.paginator import Paginator
from .serializers import (
    UserSerializer, TaskTemplateSerializer, AssignmentSerializer, 
    NotificationSerializer, ForumEntrySerializer, app_user
)
from django.db.models import Max

# ─────────────────────────────────────────────────────────────────────────────
# CORE UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _log(tag, msg, user_id=0):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {msg}")
    if user_id:
        try:
            user = app_user.objects.get(id=user_id)
            system_log.objects.create(user=user, action=f"[{tag}] {msg}")
        except Exception:
            pass

def _err(tag, msg, exc=None, user_id=0):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ [{tag}] ERROR: {msg}")
    if exc:
        traceback.print_exc()

def paginate_and_search(queryset, page=1, page_size=10, search=None, search_fields=None):
    if search and search_fields:
        query = Q()
        for field in search_fields:
            query |= Q(**{f"{field}__icontains": search})
        queryset = queryset.filter(query)

    paginator = Paginator(queryset, page_size)
    try:
        page_obj = paginator.get_page(page)
    except Exception:
        page_obj = paginator.get_page(1)

    return {
        "total": paginator.count,
        "total_pages": paginator.num_pages,
        "current_page": page_obj.number,
        "page_size": page_size,
        "data": page_obj.object_list
    }

def _check_permission(req_user_id, target_user_id=None, action="edit"):
    """
    Unified Permission Helper.
    Returns (bool permitted, app_user object or None).
    Hierarchy:
    - Admin: Full Control
    - Manager: Manage all except Admins
    - Employee: No management rights
    """
    try:
        # 🛡️ Safety: Handle non-numeric or invalid IDs from legacy sessions/hot-reloads
        if req_user_id is None or not str(req_user_id).strip().isdigit():
            _log("AUTH-PERM", f"Blocked invalid/null req_user_id: {req_user_id}")
            return False, None
            
        req_user = app_user.objects.get(id=req_user_id, deleted=False)
        req_role = str(req_user.role).lower()
        
        if req_role == 'admin':
            return True, req_user
            
        if req_role == 'manager':
            # Managers cannot touch Admins
            if target_user_id:
                target_user = app_user.objects.filter(id=target_user_id).first()
                if target_user and str(target_user.role).lower() == 'admin':
                    return False, req_user
            return True, req_user
            
        return False, req_user
    except Exception:
        return False, None

# ─────────────────────────────────────────────────────────────────────────────
# AUTH (STEP 1)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def login_user(request):
    """
    Step 1: Proper Login API
    Authenticates user, checks status, and returns serialized user data.
    """
    email = str(request.data.get('email', '')).strip()
    password = str(request.data.get('password', '')).strip()
    _log("LOGIN", f"Attempting login for: {email}")

    try:
        user = app_user.objects.filter(email__iexact=email, password=password, deleted=False).first()
        
        if not user:
            _log("LOGIN", f"❌ Invalid credentials: {email}")
            return Response({"status": "error", "message": "Invalid email or password"}, status=401)

        # 🛡️ Security Check: Status
        status = str(user.status).lower()
        if status == 'inactive':
            _log("LOGIN", f"⛔ Blocked inactive user: {email}")
            return Response({"status": "error", "message": "Account deactivated. Contact Admin."}, status=403)
        elif status == 'pending':
            _log("LOGIN", f"🕒 Blocked pending user: {email}")
            return Response({"status": "error", "message": "Account pending Admin approval."}, status=403)

        serializer = UserSerializer(user)
        _log("LOGIN", f"✅ Success: {user.name} ({user.role})")
        return Response({"status": "success", "user": serializer.data})
    except Exception as e:
        _err("LOGIN", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['GET'])
def get_pending_users(request):
    """
    Returns users with 'pending' status for admin approval.
    """
    try:
        users = app_user.objects.filter(status__iexact='pending', deleted=False)
        return Response(UserSerializer(users, many=True).data)
    except Exception as e:
        _err("PENDING-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def approve_user(request):
    """
    Approves or rejects a pending user registration.
    """
    uid        = request.data.get('user_id')
    new_status = request.data.get('status', 'active')
    try:
        user = app_user.objects.get(pk=uid, deleted=False)
        user.status = new_status
        user.save()
        
        msg = "Your account has been activated. Welcome to Campus Connection!" \
              if new_status.lower() == 'active' else "Your registration was rejected. Contact admin."
        _add_notif_logic(uid, "ACCOUNT UPDATE", msg)
        
        return Response({"status": "success"})
    except app_user.DoesNotExist:
        return Response({"status": "error", "message": "User not found"}, status=404)
    except Exception as e:
        _err("APPROVE-USER", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

        # ─────────────────────────────────────────────────────────────────────────────
# MASTER DATA (STEP 2)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_master_data(request):
    """
    Returns lists of statuses, priorities, and roles for the frontend dropdowns.
    """
    try:
        data = {
            "statuses": list(statusoption.objects.values_list('name', flat=True)),
            "priorities": list(priorityoption.objects.values_list('name', flat=True)),
            "roles": ["admin", "manager", "employee"], # Fixed roles for safety
            "server_time": datetime.now().isoformat()
        }
        return Response(data)
    except Exception as e:
        _err("MASTER-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def update_master_data(request):
    """
    Updates the available options for Status or Priority.
    """
    data_type = request.data.get('type')   # 'status' | 'priority'
    options   = request.data.get('options', [])
    
    model_map = {'status': statusoption, 'priority': priorityoption}
    Model = model_map.get(data_type)
    
    if not Model:
        return Response({"status": "error", "message": "Invalid master data type"}, status=400)
    
    try:
        clean_options = [o.strip() for o in options if o.strip()]
        
        # Safely determine which options to delete (not in use)
        # For simplicity in this 'rebuild', we overwrite unless it's a critical error
        # In a real system, we'd check ForeignKeys.
        
        # Delete old options not in the new list
        Model.objects.exclude(name__in=clean_options).delete()
        
        # Create new ones
        for name in clean_options:
            Model.objects.get_or_create(name=name)
            
        _log("MASTER-UPDATE", f"Successfully updated {data_type} options")
        return Response({"status": "success", "message": f"{data_type.capitalize()} options updated"})
    except Exception as e:
        _err("MASTER-UPDATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# USER MANAGEMENT (STEP 3)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_employees(request):
    """
    Step 3: Proper Paginated & Searchable Employee List
    Authorization: Admins/Managers only.
    """
    req_user_id = request.query_params.get('req_user_id')
    permitted, req_user = _check_permission(req_user_id)
    
    if not permitted:
        return Response({"status": "error", "message": "Permission denied"}, status=403)

    try:
        search = request.query_params.get('search')
        page   = int(request.query_params.get('page', 1))
        size   = int(request.query_params.get('page_size', 10))
        
        # Filter Logic:
        # Admins see everyone (including other admins)
        # Managers see everyone EXCEPT admins (to prevent unauthorized access)
        qs = app_user.objects.filter(deleted=False)
        if req_user.role == 'manager':
            qs = qs.exclude(role__iexact='admin')
        
        pager = paginate_and_search(qs, page, size, search, ['name', 'email', 'phone'])
        
        serializer = UserSerializer(pager['data'], many=True)
        pager['data'] = serializer.data
        
        return Response(pager)
    except Exception as e:
        _err("EMPLOYEES-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def create_employee(request):
    """
    Creates a new user with one of the fixed roles (admin, manager, employee).
    Authorization: Admins can create anyone. Managers cannot create admins.
    """
    data = request.data
    req_user_id = data.get('req_user_id') or data.get('admin_id')
    
    permitted, req_user = _check_permission(req_user_id)
    if not permitted:
        return Response({"status": "error", "message": "Permission denied"}, status=403)

    _log("EMP-CREATE", f"name={data.get('name')} email={data.get('email')} by={req_user.name}")
    
    try:
        if app_user.objects.filter(email=data.get('email'), deleted=False).exists():
            return Response({"status": "error", "message": "Email already exists"}, status=400)
        
        role = str(data.get('role', 'employee')).lower()
        
        # Manager Protection: Cannot create an admin
        if req_user.role == 'manager' and role == 'admin':
             return Response({"status": "error", "message": "Managers cannot create Admin accounts"}, status=403)
             
        if role not in ['admin', 'manager', 'employee']:
            return Response({"status": "error", "message": "Invalid role selected"}, status=400)

        phone = data.get('phone')
        if not phone or str(phone).strip() == "":
            phone = None

        user = app_user.objects.create(
            name=data.get('name'),
            email=data.get('email'),
            password=data.get('password'),
            phone=phone,
            role=role,
            status='active'
        )
        _log("EMP-CREATE", f"✅ Created user_id={user.id}")
        return Response({"status": "success", "user_id": user.id})
    except Exception as e:
        _err("EMP-CREATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def update_employee(request):
    """
    Updates an existing user's profile.
    Authorization: Admin/Manager only. Manager cannot edit Admin.
    """
    user_id = request.data.get('user_id')
    req_user_id = request.data.get('req_user_id') or request.data.get('admin_id')
    
    permitted, req_user = _check_permission(req_user_id, target_user_id=user_id)
    if not permitted:
        return Response({"status": "error", "message": "Permission denied: Managers cannot modify Admins"}, status=403)

    updates = request.data.get('updates', {})
    _log("EMP-UPDATE", f"user_id={user_id} by={req_user.name}")
    
    try:
        user = app_user.objects.filter(id=user_id, deleted=False).first()
        if not user:
            return Response({"status": "error", "message": "User not found"}, status=404)
        
        for field, value in updates.items():
            if hasattr(user, field):
                # Handle unique phone constraint for empty strings
                if field == 'phone' and (not value or str(value).strip() == ""):
                    setattr(user, field, None)
                else:
                    setattr(user, field, value)
        
        user.save()
        _log("EMP-UPDATE", f"✅ Updated user_id={user_id}")
        return Response({"status": "success"})
    except Exception as e:
        _err("EMP-UPDATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def delete_employee(request):
    """
    Soft deletes a user.
    Authorization: Admin/Manager only. Manager cannot delete Admin.
    """
    user_id = request.data.get('user_id')
    req_user_id = request.data.get('req_user_id') or request.data.get('admin_id')
    
    permitted, req_user = _check_permission(req_user_id, target_user_id=user_id)
    if not permitted:
        return Response({"status": "error", "message": "Permission denied: Managers cannot delete Admins"}, status=403)

    _log("EMP-DELETE", f"user_id={user_id} by={req_user.name}")
    
    try:
        updated = app_user.objects.filter(id=user_id, deleted=False).update(deleted=True)
        if not updated:
            return Response({"status": "error", "message": "User not found"}, status=404)
            
        _log("EMP-DELETE", f"✅ Soft deleted user_id={user_id}")
        return Response({"status": "success"})
    except Exception as e:
        _err("EMP-DELETE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['GET'])
def get_employee_status(request):
    """
    Returns the current status of all employees (Working/Idle).
    """
    try:
        users = app_user.objects.filter(deleted=False, role__iexact='employee')
        result = {}
        for u in users:
            active = assignment.objects.filter(
                assigned_to=u, 
                deleted=False
            ).select_related('status').filter(status__name__iexact='in progress').first()
            
            result[str(u.id)] = {
                "name": u.name,
                "status": "Working" if active else "Idle",
                "current_task": active.task.id if active else "-",
            }
        return Response(result)
    except Exception as e:
        _err("EMP-STATUS", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# TASK LIBRARY (STEP 4)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_library_all(request):
    """
    Step 4: Proper Paginated & Searchable Task Library
    """
    try:
        search = request.query_params.get('search')
        page   = int(request.query_params.get('page', 1))
        size   = int(request.query_params.get('page_size', 10))
        
        qs = task_management.objects.filter(deleted=False)
        pager = paginate_and_search(qs, page, size, search, ['title', 'description'])
        
        serializer = TaskTemplateSerializer(pager['data'], many=True)
        pager['data'] = serializer.data
        return Response(pager)
    except Exception as e:
        _err("LIBRARY-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def create_task_template(request):
    """
    Creates a master task template. Validate priority name.
    """
    data = request.data
    title = data.get('title')
    _log("TASK-CREATE", f"title={title}")

    try:
        # Resolve Priority (dynamic)
        p_name = data.get('priority', 'Medium')
        priority = priorityoption.objects.filter(name__iexact=p_name).first()
        if not priority:
            priority = priorityoption.objects.first() # Default fallback

        task = task_management.objects.create(
            title=title,
            description=data.get('description', ''),
            priority=priority,
            created_by=data.get('admin_name', 'Admin')
        )
        _log("TASK-CREATE", f"✅ Created task_id={task.id}")
        return Response({"status": "success", "task_id": task.id})
    except Exception as e:
        _err("TASK-CREATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def update_task_template(request):
    """
    Updates a global task template.
    """
    task_id = request.data.get('task_id')
    updates = request.data.get('updates', {})
    _log("TASK-UPDATE", f"task_id={task_id}")

    try:
        task = task_management.objects.filter(id=task_id, deleted=False).first()
        if not task:
            return Response({"status": "error", "message": "Task not found"}, status=404)

        for field, value in updates.items():
            if field == 'priority':
                p = priorityoption.objects.filter(name__iexact=value).first()
                if p: task.priority = p
            elif hasattr(task, field):
                setattr(task, field, value)
        
        task.save()
        return Response({"status": "success"})
    except Exception as e:
        _err("TASK-UPDATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def delete_task_template(request):
    """
    Soft deletes a task template.
    """
    task_id = request.data.get('task_id')
    try:
        updated = task_management.objects.filter(id=task_id, deleted=False).update(deleted=True)
        if not updated:
            return Response({"status": "error", "message": "Task not found"}, status=404)
        return Response({"status": "success"})
    except Exception as e:
        _err("TASK-DELETE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

# ─────────────────────────────────────────────────────────────────────────────
# ASSIGNMENTS (STEP 4)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
def manage_assignments(request):
    """
    Handles fetching and creating assignments.
    """
    if request.method == 'GET':
        try:
            emp_id = request.query_params.get('emp_id')
            search = request.query_params.get('search')
            page   = int(request.query_params.get('page', 1))
            size   = int(request.query_params.get('page_size', 10))
            
            qs = assignment.objects.filter(deleted=False)
            if emp_id:
                qs = qs.filter(assigned_to_id=emp_id)
            
            pager = paginate_and_search(qs, page, size, search, ['task__title', 'task__description'])
            
            serializer = AssignmentSerializer(pager['data'], many=True)
            pager['data'] = serializer.data
            return Response(pager)
        except Exception as e:
            _err("ASSIGN-GET", str(e), exc=True)
            return Response({"status": "error", "message": str(e)}, status=500)

    elif request.method == 'POST':
        data = request.data
        task_id = data.get('task_id')
        emp_id  = data.get('emp_id')
        _log("ASSIGN-CREATE", f"task={task_id} to={emp_id}")
        
        try:
            task = task_management.objects.get(id=task_id)
            user = app_user.objects.get(id=emp_id)
            
            # Default first status if available
            default_status = statusoption.objects.first()
            
            new_assign = assignment.objects.create(
                task=task,
                assigned_to=user,
                deadline=data.get('deadline'),
                assigned_by=data.get('assigned_by', 'Admin'),
                status=default_status
            )
            return Response({"status": "success", "assignment_id": new_assign.id})
        except Exception as e:
            _err("ASSIGN-CREATE", str(e), exc=True)
            return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def update_assignment(request):
    """
    Updates an assignment - Status, Deadline, or Reassign (User).
    """
    assign_id = request.data.get('assignment_id') or request.data.get('id')
    updates   = request.data.get('updates', {})
    _log("ASSIGN-UPDATE", f"id={assign_id}")

    try:
        assign = assignment.objects.filter(id=assign_id, deleted=False).first()
        if not assign:
            return Response({"status": "error", "message": "Assignment not found"}, status=404)

        for field, value in updates.items():
            if field == 'status':
                s = statusoption.objects.filter(name__iexact=value).first()
                if s: assign.status = s
            elif field == 'assigned_to_id' or field == 'emp_id':
                 u = app_user.objects.filter(id=value).first()
                 if u: assign.assigned_to = u
            elif hasattr(assign, field):
                setattr(assign, field, value)
        
        assign.save()
        return Response({"status": "success"})
    except Exception as e:
        _err("ASSIGN-UPDATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def delete_assignment(request):
    """
    Soft deletes an assignment.
    """
    assign_id = request.data.get('assignment_id') or request.data.get('id')
    try:
        updated = assignment.objects.filter(id=assign_id, deleted=False).update(deleted=True)
        if not updated:
            return Response({"status": "error", "message": "Assignment not found"}, status=404)
        return Response({"status": "success"})
    except Exception as e:
        _err("ASSIGN-DELETE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

# ─────────────────────────────────────────────────────────────────────────────
# STATS (STEP 5)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_stats(request):
    """
    Returns aggregate stats for the dashboard.
    """
    try:
        data = {
            "total_tasks": task_management.objects.filter(deleted=False).count(),
            "total_assignments": assignment.objects.filter(deleted=False).count(),
            "total_employees": app_user.objects.filter(role='employee', deleted=False).count(),
            "completed_tasks": assignment.objects.filter(status__name__iexact='Completed', deleted=False).count(),
        }
        return Response(data)
    except Exception as e:
        _err("STATS", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS (STEP 6)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_notifications(request):
    """
    Fetches paginated notifications for a user.
    """
    try:
        user_id = request.query_params.get('user_id', 1)
        page    = int(request.query_params.get('page', 1))
        size    = int(request.query_params.get('page_size', 20))
        
        qs = notification.objects.filter(user_id=user_id)
        pager = paginate_and_search(qs, page, size)
        
        serializer = NotificationSerializer(pager['data'], many=True)
        pager['data'] = serializer.data
        return Response(pager)
    except Exception as e:
        _err("NOTIF-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def mark_notif_read(request):
    notif_id = request.data.get('id')
    notification.objects.filter(id=notif_id).update(status='read')
    return Response({"status": "success"})

@api_view(['POST'])
def delete_notification(request):
    notif_id = request.data.get('id')
    notification.objects.filter(id=notif_id).delete()
    return Response({"status": "success"})

@api_view(['POST'])
def mark_all_notifs_read(request):
    user_id = request.data.get('user_id')
    notification.objects.filter(user_id=user_id, status='unread').update(status='read')
    return Response({"status": "success"})

@api_view(['POST'])
def clear_all_notifications(request):
    user_id = request.data.get('user_id')
    notification.objects.filter(user_id=user_id).delete()
    return Response({"status": "success"})

@api_view(['POST'])
def create_notification(request):
    user_id = request.data.get('user_id')
    title   = request.data.get('title', 'System Alert')
    message = request.data.get('message')
    try:
        user = app_user.objects.get(id=user_id)
        notification.objects.create(user=user, title=title, message=message)
        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

# ─────────────────────────────────────────────────────────────────────────────
# FORUM (STEP 6)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_forum_entries(request):
    """
    Fetches chat messages. If user_id is provided, fetches the specific chat history.
    Otherwise fetches all (original behavior).
    """
    try:
        user_id = request.query_params.get('user_id')
        search = request.query_params.get('search')
        page   = int(request.query_params.get('page', 1))
        size   = int(request.query_params.get('page_size', 50)) # Larger page for chat
        
        qs = forum_entry.objects.filter(deleted=False)
        if user_id:
            qs = qs.filter(user_id=user_id)
            
        pager = paginate_and_search(qs.order_by('dtm_created'), page, size, search, ['message', 'user__name'])
        
        serializer = ForumEntrySerializer(pager['data'], many=True)
        pager['data'] = serializer.data
        return Response(pager)
    except Exception as e:
        _err("FORUM-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def create_forum_entry(request):
    """
    Creates a chat message. 
    `user_id` is the 'Chat Owner' (the employee/student).
    `sender_role` identifies if it's the employee or an admin.
    """
    user_id = request.data.get('user_id')
    message = request.data.get('message')
    role    = request.data.get('sender_role', 'user')
    try:
        user = app_user.objects.get(id=user_id)
        # Mark as unread if coming from user (to alert admin)
        is_read = (role == 'admin')
        forum_entry.objects.create(user=user, message=message, sender_role=role, is_read=is_read)
        
        # 🔔 IMMEDIATE NOTIFICATION
        if role == 'user':
            # Notify Admin (user_id=1)
            notification.objects.create(
                user_id=1, 
                title="NEW COMMUNITY MESSAGE", 
                message=f"💬 {user.name} sent a message: {message[:50]}..."
            )
        else:
            # Notify Employee (the user_id targeted in the chat)
            notification.objects.create(
                user=user, 
                title="COMMUNITY REPLY", 
                message=f"💬 Management replied: {message[:50]}..."
            )

        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['GET'])
def get_chat_users(request):
    """
    Returns a list of ALL users (directory), with unread message counts and latest activity prioritized.
    Used by Admins to manage support chats.
    """
    req_user_id = request.query_params.get('req_user_id')
    permitted, req_user = _check_permission(req_user_id)
    
    if not permitted:
        return Response({"status": "error", "message": "Permission denied"}, status=403)

    try:
        # Get all users who are not deleted and not the requester themselves
        users = app_user.objects.filter(deleted=False).exclude(id=req_user.id)
        
        result = []
        for u in users:
            # unread_count: messages sent by 'user' (employee) that haven't been read by admin
            unread_count = forum_entry.objects.filter(user=u, sender_role='user', is_read=False, deleted=False).count()
            last_msg = forum_entry.objects.filter(user=u, deleted=False).order_by('-dtm_created').first()
            
            result.append({
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "profile_image": getattr(u, 'profile_image', ''),
                "unread_count": unread_count,
                "last_message": last_msg.message if last_msg else "",
                "last_time": last_msg.dtm_created if last_msg else None
            })
            
        # Sort logic: 
        # 1. Unread count (desc)
        # 2. Activity Time (desc) - use timestamp or 0 if None
        # 3. Name (asc) - handled by reversing the specific keys
        result.sort(key=lambda x: (
            x['unread_count'], 
            x['last_time'].timestamp() if x['last_time'] else 0
        ), reverse=True)
        
        return Response(result)
    except Exception as e:
        _err("CHAT-USERS", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def mark_forum_read(request):
    """
    Marks all messages in a specific user's chat as read by the admin.
    """
    user_id = request.data.get('user_id')
    try:
        forum_entry.objects.filter(user_id=user_id, sender_role='user', is_read=False).update(is_read=True)
        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def reply_forum_entry(request):
    # This is a legacy endpoint, we now use create_forum_entry with role='admin'
    return create_forum_entry(request)

@api_view(['POST'])
def delete_forum_entry(request):
    forum_id = request.data.get('forum_id')
    forum_entry.objects.filter(id=forum_id).update(deleted=True)
    return Response({"status": "success"})

# ─────────────────────────────────────────────────────────────────────────────
# TASK LIFECYCLE ACTIONS
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
def start_task(request):
    assign_id = request.data.get('assign_id')
    try:
        status = statusoption.objects.filter(name__iexact='In Progress').first()
        assignment.objects.filter(id=assign_id).update(status=status, start_date=timezone.now().date())
        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def complete_task(request):
    assign_id = request.data.get('assign_id')
    try:
        status = statusoption.objects.filter(name__iexact='Completed').first()
        assignment.objects.filter(id=assign_id).update(status=status, end_date=timezone.now().date())
        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def request_approval(request):
    assign_id = request.data.get('assign_id')
    comment   = request.data.get('comment', '')
    try:
        status = statusoption.objects.filter(name__iexact='Awaiting Approval').first()
        assignment.objects.filter(id=assign_id).update(status=status, comments=comment)
        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def check_overdue(request):
    """
    Manually triggers an overdue check (for sync purposes).
    """
    today = date.today()
    try:
        overdue_status, _ = statusoption.objects.get_or_create(name='Overdue')
        qs = assignment.objects.filter(
            deleted=False, 
            deadline__lt=today, 
            notified_overdue=False
        ).exclude(status__name__iexact='Completed')
        
        count = 0
        for asgn in qs:
            asgn.status = overdue_status
            asgn.notified_overdue = True
            asgn.save()
            count += 1
            
        return Response({"status": "sync_complete", "updated": count})
    except Exception as e:
        _err("OVERDUE-CHECK", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS & REPORTS
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_reports(request):
    """
    Returns a list of all users and their task completion metrics.
    """
    try:
        users = app_user.objects.filter(deleted=False)
        report = []
        for u in users:
            u_tasks = assignment.objects.filter(assigned_to=u, deleted=False)
            completed = u_tasks.filter(status__name__iexact='Completed').count()
            overdue   = u_tasks.filter(status__name__iexact='Overdue').count()
            total     = u_tasks.count()
            
            report.append({
                "user_id": u.id,
                "name": u.name,
                "total": total,
                "completed": completed,
                "overdue": overdue,
                "completion_rate": round(completed / total * 100, 1) if total else 0,
            })
        return Response(report)
    except Exception as e:
        _err("REPORTS", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['GET'])
def get_recent_activity(request):
    """
    Returns the most recent global activity.
    """
    try:
        qs = assignment.objects.filter(deleted=False).select_related(
            'task', 'assigned_to', 'status'
        ).order_by('-dtm_created')[:10]
        return Response(AssignmentSerializer(qs, many=True).data)
    except Exception as e:
        _err("ACTIVITY", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['GET'])
def get_user_summary(request):
    """
    Returns stats for a specific user (Today's tasks, pending, etc).
    """
    user_id = request.query_params.get('user_id')
    if not user_id:
        return Response({"error": "user_id required"}, status=400)
        
    try:
        today = date.today()
        qs = assignment.objects.filter(assigned_to_id=user_id, deleted=False)
        
        return Response({
            "today_tasks": qs.filter(deadline=today).count(),
            "pending":     qs.filter(status__name__iexact='Pending').count(),
            "completed":   qs.filter(status__name__iexact='Completed').count(),
            "overdue":     qs.filter(status__name__iexact='Overdue').count(),
        })
    except Exception as e:
        _err("USER-SUMMARY", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM CHECK
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
def run_system_check(request):
    """
    Automated background task to check for overdue items and system health.
    Expects to be called periodically by the frontend or a cron job.
    """
    today = date.today()
    try:
        overdue_status, _ = statusoption.objects.get_or_create(name='Overdue')

        # 1. Update Newly Overdue Tasks
        newly_overdue = assignment.objects.filter(
            deleted=False, 
            deadline__lt=today, 
            notified_overdue=False
        ).exclude(status__name__iexact='Completed').select_related('task', 'assigned_to')

        newly_list = list(newly_overdue)
        for asgn in newly_list:
            asgn.status = overdue_status
            asgn.notified_overdue = True
            asgn.save()
            
            # Notify the employee
            _add_notif_logic(asgn.assigned_to_id, f"🚨 Task Overdue: '{asgn.task.title}' needs immediate attention!")

        # 2. Update Not Started status
        not_started = assignment.objects.filter(
            deleted=False, 
            start_date__isnull=True, 
            notified_start=False,
            status__name__iexact='Pending'
        ).select_related('task', 'assigned_to')
        
        for asgn in not_started:
            asgn.notified_start = True
            asgn.save()

        # 3. Aggregate Stats for Summary
        total_overdue = assignment.objects.filter(deleted=False, status__name__iexact='Overdue').count()
        
        parts = []
        if total_overdue > 0: parts.append(f"{total_overdue} overdue")
        if len(newly_list) > 0: parts.append(f"{len(newly_list)} newly flagged")

        if parts:
            summary = "📊 System Alert: " + ", ".join(parts)
            # Notify main admin (ID 1)
            _add_notif_logic(1, "SYSTEM SUMMARY", summary)
            return Response({"status": "ok", "summary": summary})
            
        return Response({"status": "ok", "summary": "System healthy"})
    except Exception as e:
        _err("SYSTEM-CHECK", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

def _add_notif_logic(user_id, title, message):
    """Internal helper to add notifications without full API overhead."""
    try:
        user = app_user.objects.get(id=user_id)
        notification.objects.create(user=user, title=title, message=message)
    except Exception:
        pass
