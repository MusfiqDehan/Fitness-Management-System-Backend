from django.conf import settings
from django.db import models
from django.utils.text import slugify


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
    desktop_url = models.URLField(max_length=1000, help_text="Media URL for desktop (1920x1080). Required.")
    laptop_url = models.URLField(max_length=1000, blank=True, help_text="Media URL for laptop (1366x768)")
    tablet_url = models.URLField(max_length=1000, blank=True, help_text="Media URL for tablet (768x1024)")
    mobile_url = models.URLField(max_length=1000, blank=True, help_text="Media URL for mobile (375x667)")
    cta_text = models.CharField(max_length=100, blank=True, help_text="Call-to-action button label")
    cta_link = models.CharField(max_length=500, blank=True, help_text="Call-to-action URL or path")
    alt_text = models.CharField(max_length=255, blank=True, default="", help_text="Accessible description for the banner media")
    start_date = models.DateField(null=True, blank=True, help_text="Date from which the banner is visible")
    end_date = models.DateField(null=True, blank=True, help_text="Date after which the banner is hidden")
    position = models.PositiveIntegerField(default=0, help_text="Display order; lower numbers appear first")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'created_at']

    def __str__(self):
        return f"{self.title} (position {self.position})"


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
    title = models.CharField(max_length=200, blank=True, default="", help_text="Primary text shown on the promo banner")
    subtitle = models.CharField(max_length=200, blank=True, default="", help_text="Secondary text shown on the promo banner")
    image_url = models.URLField(max_length=1000, blank=True, help_text="Primary/fallback image URL")
    desktop_image_url = models.URLField(max_length=1000, blank=True)
    tablet_image_url = models.URLField(max_length=1000, blank=True)
    mobile_image_url = models.URLField(max_length=1000, blank=True)
    cta_text = models.CharField(max_length=100, blank=True, default="", help_text="Optional call-to-action label")
    link_url = models.CharField(max_length=500, blank=True, help_text="Target URL when the banner is clicked")
    alt_text = models.CharField(max_length=255, blank=True, default="", help_text="Accessible description for the promo image")
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(null=True, blank=True, help_text="Date from which the banner is visible")
    end_date = models.DateField(null=True, blank=True, help_text="Date after which the banner is hidden")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']

    def __str__(self):
        return f"{self.get_banner_type_display()} banner (id={self.pk})"


class PageContent(models.Model):
    """
    Stores editable content for individually named site pages (e.g. 'Home', 'About').
    page_name is a unique identifier matching the AVAILABLE_PAGES list on the frontend.
    Only one content record per page_name is allowed.
    """
    page_name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Internal page identifier, e.g. 'Home', 'About', 'Branches'",
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
        blank=True,
        related_name='cms_blogs'
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title