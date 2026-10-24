# PO-token server for yt-dlp (bgutil). The upstream image listens on 0.0.0.0 (IPv4 only),
# but Railway's private network is IPv6, so the worker could never reach it.
# Keep the tag's major version in step with bgutil-ytdlp-pot-provider in backend/pyproject.toml.
FROM brainicism/bgutil-ytdlp-pot-provider:2.0.2
CMD ["--host", "::"]
