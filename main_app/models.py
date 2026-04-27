from django.db import models
from django.utils.text import slugify
from django.conf import settings


class Banner(models.Model):
    BACKGROUND_TYPE_CHOICES = (
        ('image', 'Image'),
        ('video', 'Video'),
    )

    background_type = models.CharField(
        max_length=10,
        choices=BACKGROUND_TYPE_CHOICES
    )

    background_file = models.FileField(
        upload_to='banners/backgrounds/'
    )

    title1 = models.CharField(
        max_length=100,
        help_text="Small title"
    )

    title2 = models.CharField(
        max_length=200,
        help_text="Big title"
    )

    title3 = models.CharField(
        max_length=150,
        help_text="Medium title"
    )

    fitness_name = models.CharField(
        max_length=100
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.fitness_name

# ---- club manager ---
class Facility(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class GymClub(models.Model):
    name = models.CharField(max_length=150)
    image = models.ImageField(
        upload_to='gym_clubs/',
        blank=True,
        null=True
    )
    location = models.CharField(max_length=250, blank=True, null=True)
    address = models.TextField()
    description = models.TextField(blank=True, null=True)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField()
    opening_time = models.TimeField(blank=True,
        null=True,)
    closing_time = models.TimeField(blank=True,
        null=True,)
    weekdays_hours = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="e.g., 6:00AM-10:00PM"
    )
    weekend_hours = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="e.g., 6:00AM-10:00PM"
    )
    facilities = models.ManyToManyField('Facility', related_name="gyms")
    display_order = models.PositiveIntegerField(default=0)
    website = models.URLField(blank=True, null=True)
    homepage_image = models.ImageField(
        upload_to='gym_clubs/homepage/',
        blank=True,
        null=True
    )
    show_on_homepage = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name


# ---- Contact Manager ---
class Contact(models.Model):

    STATUS_NEW = "new"
    STATUS_READ = "read"
    STATUS_RESPONDED = "responded"

    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_READ, "Read"),
        (STATUS_RESPONDED, "Responded"),
    ]

    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=20)

    preferred_club = models.ForeignKey(
        'GymClub',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contacts"
    )

    subject = models.CharField(max_length=200)
    message = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NEW
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.subject}"

# -- FitHive Support --
class FitHiveSupport(models.Model):

    STATUS_NEW = "new"
    STATUS_READ = "read"
    STATUS_RESPONDED = "responded"

    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_READ, "Read"),
        (STATUS_RESPONDED, "Responded"),
    ]

    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=20)

    # Just Text Field
    interested_in = models.CharField(max_length=255)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NEW
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.interested_in}"



# ---- Class Manager ---
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class ClassSchedule(models.Model):
    DAYS_OF_WEEK = [
        ("Monday", "Monday"),
        ("Tuesday", "Tuesday"),
        ("Wednesday", "Wednesday"),
        ("Thursday", "Thursday"),
        ("Friday", "Friday"),
        ("Saturday", "Saturday"),
        ("Sunday", "Sunday"),
    ]

    day = models.CharField(max_length=10, choices=DAYS_OF_WEEK)
    time = models.TimeField()  # 06:00:00

    def __str__(self):
        return f"{self.day} {self.time.strftime('%I:%M %p')}"

class GymClass(models.Model):
    LEVEL_CHOICES = [
        ("All Levels", "All Levels"),
        ("Beginner", "Beginner"),
        ("Intermediate", "Intermediate"),
        ("Advanced", "Advanced"),
    ]

    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to="gym_classes/", blank=True, null=True)
    description = models.TextField()

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="gym_classes"
    )

    class_duration = models.CharField(max_length=50)  # e.g. "45 min"
    people = models.PositiveIntegerField(help_text="Max number of people")
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)

    class_schedule = models.ManyToManyField(
        ClassSchedule,
        related_name="gym_classes"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_show_on_home_page = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def __str__(self):
        return self.title


class ClassBooking(models.Model):
    STATUS_CHOICES = [
        ("confirmed", "Confirmed"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="class_bookings"
    )

    gym_class = models.ForeignKey(
        "GymClass",
        on_delete=models.CASCADE,
        related_name="bookings"
    )
    phone = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="confirmed"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("user", "gym_class")

    def __str__(self):
        return f"{self.user} - {self.gym_class.title}"

# ---- Blog ---

class BlogCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Blog(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('published', 'Published'),
    )

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    image = models.ImageField(upload_to='blogs/')
    category = models.ForeignKey(
        BlogCategory,
        on_delete=models.CASCADE,
        related_name='blogs'
    )
    excerpt = models.TextField()
    description = models.TextField()
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='draft'
    )
    is_show_on_home_page = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_date = models.DateTimeField(null=True, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


# ---- package manager ---
class Package(models.Model):
    name = models.CharField(max_length=200)
    duration = models.CharField(max_length=50, help_text="e.g. '1 month', '3 months'")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    display_order = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name


class PackageFeature(models.Model):
    package = models.ForeignKey(
        Package, on_delete=models.CASCADE, related_name='features'
    )
    feature = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.feature} ({self.package.name})"


class PackageAddOn(models.Model):
    package = models.ForeignKey(
        Package, on_delete=models.CASCADE, related_name='addons'
    )
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.package.name})"


# ---- Site Banner (Hero Banner Manager) ----

class SiteBanner(models.Model):
    """
    Represents a hero/slider banner shown on the homepage.
    Supports responsive media: separate URLs for desktop, laptop, tablet, and mobile viewports.
    Supports both image and video media types.
    """
    MEDIA_TYPE_CHOICES = (
        ('image', 'Image'),
        ('video', 'Video'),
    )

    title = models.CharField(max_length=200, help_text="Main heading shown on the banner")
    subtitle = models.CharField(max_length=200, blank=True, help_text="Label/badge above the title")
    media_type = models.CharField(
        max_length=10,
        choices=MEDIA_TYPE_CHOICES,
        default='image',
    )
    desktop_url = models.URLField(max_length=1000, help_text="Media URL for desktop (1920×1080). Required.")
    laptop_url = models.URLField(max_length=1000, blank=True, help_text="Media URL for laptop (1366×768)")
    tablet_url = models.URLField(max_length=1000, blank=True, help_text="Media URL for tablet (768×1024)")
    mobile_url = models.URLField(max_length=1000, blank=True, help_text="Media URL for mobile (375×667)")
    cta_text = models.CharField(max_length=100, blank=True, help_text="Call-to-action button label")
    cta_link = models.CharField(max_length=500, blank=True, help_text="Call-to-action URL or path")
    position = models.PositiveIntegerField(default=0, help_text="Display order; lower numbers appear first")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'created_at']

    def __str__(self):
        return f"{self.title} (position {self.position})"


# ---- Promo Banner (Top-Bar / Popup Modal) ----

class PromoBanner(models.Model):
    """
    Represents a promotional banner shown either as a top-bar announcement
    or as a popup/modal overlay. Supports optional scheduling via start/end dates
    and responsive image URLs for different viewports.
    """
    BANNER_TYPE_CHOICES = (
        ('top_bar', 'Top Bar'),
        ('popup_modal', 'Popup Modal'),
    )

    banner_type = models.CharField(
        max_length=20,
        choices=BANNER_TYPE_CHOICES,
        default='top_bar',
    )
    image_url = models.URLField(max_length=1000, blank=True, help_text="Primary/fallback image URL")
    desktop_image_url = models.URLField(max_length=1000, blank=True)
    tablet_image_url = models.URLField(max_length=1000, blank=True)
    mobile_image_url = models.URLField(max_length=1000, blank=True)
    link_url = models.CharField(max_length=500, blank=True, help_text="Target URL when the banner is clicked")
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(null=True, blank=True, help_text="Date from which the banner is visible")
    end_date = models.DateField(null=True, blank=True, help_text="Date after which the banner is hidden")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_banner_type_display()} banner (id={self.pk})"


# ---- Site Settings (Singleton) ----

class SiteSettings(models.Model):
    """
    Global site-wide configuration. Designed as a singleton: only one row should
    exist at a time. The view layer enforces this via get_or_create.

    Stores:
    - Logo URL and display dimensions
    - Ordered navbar page list as JSON
    - Ordered footer page list as JSON
    """
    logo_url = models.URLField(max_length=1000, blank=True)
    logo_width = models.PositiveIntegerField(default=120, help_text="Logo display width in pixels")
    logo_height = models.PositiveIntegerField(default=40, help_text="Logo display height in pixels")
    company_name = models.CharField(max_length=200, blank=True, help_text="Optional company name shown in navbar/footer")
    navbar_pages = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered list of {page_name, label, order} objects for the navbar",
    )
    footer_pages = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered list of {page_name, label, order} objects for the footer",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Site Settings"
        verbose_name_plural = "Site Settings"

    def __str__(self):
        return "Site Settings"


# ---- Page Content (Dynamic CMS Pages) ----

class PageContent(models.Model):
    """
    Stores editable content for individually named site pages (e.g. 'Home', 'About').
    page_name is a unique identifier matching the AVAILABLE_PAGES list on the frontend.
    Only one content record per page_name is allowed.
    """
    page_name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Internal page identifier, e.g. 'Home', 'About', 'Clubs'",
    )
    title = models.CharField(max_length=255, blank=True)
    subtitle = models.CharField(max_length=255, blank=True)
    hero_image = models.URLField(max_length=1000, blank=True, help_text="Hero/header image URL")
    content = models.TextField(blank=True, help_text="Main page content (may contain HTML)")
    meta_description = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['page_name']

    def __str__(self):
        return self.page_name


# ---- Gym Schedule Manager ----

class GymSchedule(models.Model):
    """
    Represents a gym class/session schedule entry manageable from the admin dashboard.
    Displayed dynamically on the homepage ScheduleSection.
    """
    DAYS_OF_WEEK = [
        ("Monday", "Monday"),
        ("Tuesday", "Tuesday"),
        ("Wednesday", "Wednesday"),
        ("Thursday", "Thursday"),
        ("Friday", "Friday"),
        ("Saturday", "Saturday"),
        ("Sunday", "Sunday"),
    ]

    DIFFICULTY_CHOICES = [
        ("All Levels", "All Levels"),
        ("Beginner", "Beginner"),
        ("Intermediate", "Intermediate"),
        ("Advanced", "Advanced"),
    ]

    class_name = models.CharField(max_length=200)
    instructor = models.CharField(max_length=200, blank=True)
    day = models.CharField(max_length=10, choices=DAYS_OF_WEEK)
    time = models.TimeField(help_text="Start time, e.g. 06:30")
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    difficulty_level = models.CharField(
        max_length=20,
        choices=DIFFICULTY_CHOICES,
        default="All Levels"
    )
    category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'day', 'time']

    def __str__(self):
        return f"{self.class_name} - {self.day} {self.time.strftime('%H:%M')}"