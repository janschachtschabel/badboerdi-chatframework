# syntax=docker/dockerfile:1.7
FROM nginx:1.27-alpine

# Default points at localhost backend; override at runtime via -e BACKEND_URL=...
ENV BACKEND_URL=http://localhost:8000

COPY index.template.html /usr/share/nginx/html/index.template.html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY entrypoint.sh /docker-entrypoint.d/40-render-template.sh
RUN chmod +x /docker-entrypoint.d/40-render-template.sh

EXPOSE 80
