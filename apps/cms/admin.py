from django.contrib import admin
from .models import SiteBanner, PromoBanner, SiteSettings, PageContent, BlogCategory, Blog


@admin.register(SiteBanner)
class SiteBannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'position', 'is_active', 'created_at']
    list_filter = ['is_active', 'media_type']
    search_fields = ['title', 'subtitle']
    ordering = ['position', '-created_at']


@admin.register(PromoBanner)
class PromoBannerAdmin(admin.ModelAdmin):
    list_display = ['banner_type', 'is_active', 'start_date', 'end_date', 'created_at']
    list_filter = ['banner_type', 'is_active']
    search_fields = ['link_url']
    ordering = ['-created_at']


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    pass


@admin.register(PageContent)
class PageContentAdmin(admin.ModelAdmin):
    list_display = ['page_name', 'title', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['page_name', 'title']
    ordering = ['page_name']


@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Blog)
class BlogAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'status', 'is_show_on_home_page', 'published_date']
    list_filter = ['status', 'is_show_on_home_page', 'category']
    search_fields = ['title', 'description']
    prepopulated_fields = {'slug': ('title',)}
    ordering = ['-created_at']