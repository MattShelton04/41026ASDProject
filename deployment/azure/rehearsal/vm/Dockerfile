# Rehearsal "VM" for `uv run scripts/dev.py cloud rehearse` (local only, never deployed).
#
# A Docker-in-Docker host stands in for the Ubuntu 24.04 VM: its own Docker Engine (empty image
# store, so every image really comes from the rehearsal registry), root, Linux paths under
# /opt/propertyscope, and the tools cloud-init installs that propertyscope-vm.sh uses. The daemon
# configuration is cloud-init's /etc/docker/daemon.json, mounted by the rehearsal at run time.
FROM docker:28.5.1-dind

RUN apk add --no-cache bash coreutils curl findutils gawk git grep iproute2 jq sed tar util-linux

# cloud-init's last step on the real VM; propertyscope-vm.sh waits for it.
RUN install -d -m 0755 /etc/propertyscope \
    && printf 'rehearsal\n' >/etc/propertyscope/bootstrap-version \
    && touch /etc/propertyscope/bootstrap-complete

COPY --chmod=0644 rehearsal.sh /etc/propertyscope/rehearsal.sh
