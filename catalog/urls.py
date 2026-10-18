from django.urls import path

from . import views

urlpatterns = [
    path("", views.channel, name="channel"),
    path("find/", views.find, name="find"),
    path("video/<str:video_id>/", views.video, name="video"),
]
