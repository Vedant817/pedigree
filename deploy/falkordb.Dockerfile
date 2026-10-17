# FalkorDB for Render private services.
#
# Deliberately a thin wrapper over the SAME pinned image the Compose file and CI
# already use, so there is exactly one FalkorDB version in this project. The only
# change is the entrypoint, because Render private services inject $PORT and the
# upstream entrypoint always binds 6379.
FROM falkordb/falkordb:v4.22.1
COPY deploy/falkordb-entrypoint.sh /usr/local/bin/falkordb-render-entrypoint
RUN chmod +x /usr/local/bin/falkordb-render-entrypoint
ENTRYPOINT ["/usr/local/bin/falkordb-render-entrypoint"]