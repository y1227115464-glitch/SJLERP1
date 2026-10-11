FROM nginx:1.28-alpine
COPY infra/nas/nginx.conf /etc/nginx/conf.d/default.conf
COPY offline/web-dist/ /usr/share/nginx/html
RUN chmod -R a+rX /usr/share/nginx/html
