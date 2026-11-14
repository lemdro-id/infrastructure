FROM nginx:1.30-alpine@sha256:901e593c95dc85f5a729f5765516321366ef4ac401821431d408897e95287d0a
COPY ./nginx.conf /etc/nginx/nginx.conf
RUN nginx -t
