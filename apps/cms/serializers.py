from rest_framework import serializers
from .models import (
    SiteBanner,
    PromoBanner,
    SiteSettings,
    PageContent,
    BlogCategory,
    Blog,
)


# ---- Site Banner Serializer ----

class SiteBannerSerializer(serializers.ModelSerializer):
    """
    Serializer for the SiteBanner model.

    Validates that `title` and `desktop_url` are non-empty on create/update,
    since desktop media is the minimum required for a functional hero banner.
    """

    class Meta:
        model = SiteBanner
        fields = [
            'id',
            'title',
            'subtitle',
            'media_type',
            'desktop_url',
            'laptop_url',
            'tablet_url',
            'mobile_url',
            'cta_text',
            'cta_link',
            'position',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_title(self, value):
        """Ensure the banner title is not blank."""
        if not value or not value.strip():
            raise serializers.ValidationError("Banner title is required.")
        return value.strip()

    def validate_desktop_url(self, value):
        """Ensure desktop media URL is provided; it is the fallback for all viewports."""
        if not value or not value.strip():
            raise serializers.ValidationError("Desktop URL is required for a hero banner.")
        return value.strip()


# ---- Promo Banner Serializer ----

class PromoBannerSerializer(serializers.ModelSerializer):
    """
    Serializer for the PromoBanner model.

    Validates that, when both `start_date` and `end_date` are supplied,
    `end_date` is strictly after `start_date`.
    """

    class Meta:
        model = PromoBanner
        fields = [
            'id',
            'banner_type',
            'image_url',
            'desktop_image_url',
            'tablet_image_url',
            'mobile_image_url',
            'link_url',
            'is_active',
            'start_date',
            'end_date',
            'created_at',
        ]
        read_only_fields = ['created_at']

    def validate(self, attrs):
        """Cross-field validation: end_date must come after start_date when both are set."""
        start = attrs.get('start_date')
        end = attrs.get('end_date')
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"end_date": "End date must be after start date."}
            )
        return attrs


# ---- Site Settings Serializer ----

class SiteSettingsSerializer(serializers.ModelSerializer):
    """
    Serializer for the singleton SiteSettings model.

    `navbar_pages` and `footer_pages` are stored as JSON arrays of
    `{page_name, label, order}` objects.
    """

    class Meta:
        model = SiteSettings
        fields = [
            'id',
            'logo_url',
            'logo_width',
            'logo_height',
            'company_name',
            'navbar_pages',
            'footer_pages',
            'updated_at',
        ]
        read_only_fields = ['updated_at']

    def validate_logo_width(self, value):
        """Logo width must be between 40 and 600 pixels."""
        if not (40 <= value <= 600):
            raise serializers.ValidationError("Logo width must be between 40 and 600 pixels.")
        return value

    def validate_logo_height(self, value):
        """Logo height must be between 20 and 300 pixels."""
        if not (20 <= value <= 300):
            raise serializers.ValidationError("Logo height must be between 20 and 300 pixels.")
        return value


# ---- Page Content Serializer ----

class PageContentSerializer(serializers.ModelSerializer):
    """
    Serializer for the PageContent model.

    Validates that `page_name` uniqueness is maintained even during partial
    updates: a different existing record must not already own the requested name.
    """

    class Meta:
        model = PageContent
        fields = [
            'id',
            'page_name',
            'title',
            'subtitle',
            'hero_image',
            'content',
            'meta_description',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_page_name(self, value):
        """
        Validate that page_name is unique across all records.
        On update, the current instance is excluded from the uniqueness check.
        """
        if not value or not value.strip():
            raise serializers.ValidationError("Page name is required.")
        value = value.strip()
        qs = PageContent.objects.filter(page_name=value)
        # Exclude the current instance when updating
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f"A content record for page '{value}' already exists."
            )
        return value


# ---- Blog Serializers ----

class BlogCategorySerializer(serializers.ModelSerializer):
    def validate_name(self, value):
        normalized_value = value.strip()
        if not normalized_value:
            raise serializers.ValidationError('This field may not be blank.')

        existing_categories = BlogCategory.objects.filter(name__iexact=normalized_value)
        if self.instance is not None:
            existing_categories = existing_categories.exclude(pk=self.instance.pk)

        if existing_categories.exists():
            raise serializers.ValidationError('A blog category with this name already exists.')

        return normalized_value

    class Meta:
        model = BlogCategory
        fields = ['id', 'name', 'slug']


class BlogListSerializer(serializers.ModelSerializer):
    category = BlogCategorySerializer()

    class Meta:
        model = Blog
        fields = [
            'id',
            'title',
            'slug',
            'image',
            'category',
            'status',
            'published_date',
            'created_at',
            'excerpt',
        ]


class BlogDetailSerializer(serializers.ModelSerializer):
    category = BlogCategorySerializer()

    class Meta:
        model = Blog
        fields = '__all__'


class DashboardBlogSerializer(serializers.ModelSerializer):
    # Read category as nested for GET, write as PK for POST/PUT
    category = BlogCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=BlogCategory.objects.all(),
        source='category',
        write_only=True
    )
    image = serializers.ImageField(required=False)

    class Meta:
        model = Blog
        fields = [
            'id',
            'title',
            'slug',
            'excerpt',
            'description',
            'image',
            'category',
            'category_id',   # this is required for create/update
            'status',
            'is_show_on_home_page',
            'author',
            'published_date',
            'created_at',
        ]
        read_only_fields = ['author', 'published_date', 'created_at']

    def create(self, validated_data):
        # Assign author automatically
        validated_data['author'] = self.context['request'].user

        # Set published_date if status is published
        if validated_data.get('status') == 'published':
            validated_data['published_date'] = timezone.now()

        return super().create(validated_data)

    def update(self, instance, validated_data):
        if validated_data.get('status') == 'published' and not instance.published_date:
            validated_data['published_date'] = timezone.now()
        return super().update(instance, validated_data)


from django.utils import timezone