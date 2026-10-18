from django.conf import settings
from django.http import Http404
from django.shortcuts import render

from .youtube_api import YouTubeError, find_similar, get_video, list_videos, video_metadata_rows


def channel(request):
    query = request.GET.get("q", "")
    page_token = request.GET.get("page") or None
    try:
        data = list_videos(page_token=page_token, query=query)
    except YouTubeError as exc:
        status = 404 if exc.status == 404 else 502
        return render(request, "catalog/channel.html", {"error": str(exc)}, status=status)

    return render(request, "catalog/channel.html", data)


def video(request, video_id: str):
    try:
        item = get_video(video_id)
    except YouTubeError as exc:
        if exc.status == 404:
            raise Http404(str(exc)) from exc
        return render(request, "catalog/video.html", {"error": str(exc)}, status=502)

    return render(
        request,
        "catalog/video.html",
        {
            "video": item,
            "metadata": video_metadata_rows(item),
            "find_query": request.GET.get("q", ""),
        },
    )


def find(request):
    query = request.GET.get("q", "")
    if not query.strip():
        return render(request, "catalog/find.html", {"query": ""})
    try:
        data = find_similar(query)
    except YouTubeError as exc:
        status = 404 if exc.status == 404 else 502
        return render(
            request,
            "catalog/find.html",
            {"query": query, "error": str(exc)},
            status=status,
        )
    data["channel_id"] = settings.YOUTUBE_CHANNEL_ID
    return render(request, "catalog/find.html", data)
