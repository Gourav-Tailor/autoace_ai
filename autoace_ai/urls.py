from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    # Admin Interface
    path('admin/', admin.site.urls),
    
    # Root URL (http://localhost:8000/) shows Login Page
    path('', auth_views.LoginView.as_view(template_name='audio_analytics/login.html'), name='login'),
    
    # Logout URL
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    
    # App Routes (Dashboard, Upload, Batches)
    path('', include('audio_analytics.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)