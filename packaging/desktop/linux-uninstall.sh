#!/bin/sh
# Delete only paths recorded by this installer; preserve other user files.
set -eu
are_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
[ -f "$are_dir/.are-uninstall-files" ] && [ -f "$are_dir/.are-uninstall-dirs" ] || { echo 'Installer inventory missing' >&2; exit 2; }
# Validate the entire inventory before changing anything. Parent symlinks must
# not redirect deletion outside the installation.
for are_inventory in "$are_dir/.are-uninstall-files" "$are_dir/.are-uninstall-dirs"; do
    while IFS= read -r are_file; do
        case "$are_file" in ''|/*|../*|*/../*|*/..|.|..) echo 'Invalid installer inventory' >&2; exit 2 ;; esac
        are_parent=$(realpath -m -- "$(dirname -- "$are_dir/$are_file")")
        case "$are_parent/" in "$are_dir/"*) ;; *) echo 'Installed directory was replaced by an external symlink; refusing uninstall' >&2; exit 2 ;; esac
    done < "$are_inventory"
done
while IFS= read -r are_file; do
    rm -f -- "$are_dir/$are_file"
done < "$are_dir/.are-uninstall-files"
while IFS= read -r are_subdir; do
    case "$are_subdir" in ''|/*|../*|*/../*|*/..|.|..) echo 'Invalid directory inventory' >&2; exit 2 ;; esac
    rmdir -- "$are_dir/$are_subdir" 2>/dev/null || :
done < "$are_dir/.are-uninstall-dirs"
rm -f -- "$are_dir/.are-uninstall-files" "$are_dir/.are-uninstall-dirs" "$are_dir/uninstall.sh"
if rmdir -- "$are_dir" 2>/dev/null; then
    echo 'ARE SoftwareGPU uninstalled'
else
    printf 'ARE SoftwareGPU uninstalled; additional user files retained in %s\n' "$are_dir"
fi
