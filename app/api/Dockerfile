# Runtime image for the storefront API. The jar is built and tested by Maven in the
# CI build (ci/buildspec-build.yml) before this image is assembled, so the image
# contains only the JRE and the application.
FROM public.ecr.aws/amazoncorretto/amazoncorretto:21-al2023-headless

WORKDIR /app
COPY target/storefront-api.jar /app/storefront-api.jar

# Run as an unprivileged user.
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/storefront-api.jar"]
