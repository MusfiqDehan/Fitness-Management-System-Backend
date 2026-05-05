from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone

# -------------------------------
# User Manager
# -------------------------------
class UserManager(BaseUserManager):
    def create_user(self, email=None, phone=None, password=None, role='student', **extra_fields):
        if not email and not phone:
            raise ValueError("User must have either email or phone")

        if password and not extra_fields.get("password_set_at"):
            extra_fields["password_set_at"] = timezone.now()

        user = self.model(
            email=self.normalize_email(email) if email else None,
            phone=phone,
            role=role,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        # Superuser defaults
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "superuser")
        extra_fields.setdefault("email_verified", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email=email, password=password, **extra_fields)

# -------------------------------
# User Model
# -------------------------------
class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ('student', 'Student'),
        ('instructor', 'Instructor'),
        ('staff', 'Staff'),
        ('admin', 'Admin'),
        ('superuser', 'Superuser'),
    )

    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=100, blank=True, default='')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='student')
    tenant = models.ForeignKey(
        'tenancy.Tenant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        help_text='Tenant this user belongs to. Public platform users can leave this empty.',
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # allows admin access in Django admin
    email_verified = models.BooleanField(default=False)
    password_set_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        # Display email/phone with role
        return f"{self.email or self.phone} ({self.role})"



class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student_profile')

    full_name = models.CharField(max_length=100)
    age = models.IntegerField(null=True, blank=True)
    weight = models.FloatField(null=True, blank=True)
    height = models.FloatField(null=True, blank=True)
    emergency_contact = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.full_name


class InstructorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='instructor_profile')

    full_name = models.CharField(max_length=100)
    experience_years = models.IntegerField(null=True, blank=True)
    specialization = models.CharField(max_length=200, blank=True)
    bio = models.TextField(blank=True)

    def __str__(self):
        return self.full_name
