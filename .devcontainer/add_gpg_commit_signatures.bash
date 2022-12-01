#!/bin/bash -i
(
set -e
cat << EOF > gpg.key
# Please add here your gpg public key long format export, for importing!!
# Save and exit will import the gpg public key.
# gpg --list-secret-keys --keyid-format=long
# format -> e.g. rsa4096/<key-id>
# gpg --armor --export <key-id>
EOF
nano gpg.key
gpg --import gpg.key
rm gpg.key

git config --global commit.gpgSign true
git config --global tag.gpgSign true
)
exit 0