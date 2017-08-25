# trac-bitbucketsync

BitbucketSyncPlugin syncs Bitbucket repository with local repository used by Trac.

See https://trac-hacks.org/wiki/BitbucketSyncPlugin for more info.

## Installation

Install `mercurial` dependency and the `trac-bitbucketsync` plugin using easy_install:
```
easy_install mercurial
easy_install https://github.com/phuc77/trac-bitbucketsync/zipball/master
```

## Bitbucket Webhooks

Open your repository on bitbucket.org and go to `Settings` -> `Webhooks` and click on `Add webhook` and use as URL:
```
https://example.com/bitbucketsync
```
Replace `example.com` with your hostname!

## Clone your repo locally using SSH keys

In this example I use `/var/lib/git` as base directory, apache2 runs as www-data on Debian/Ubuntu.

### Setup SSH keys for www-data account:
```
cd /home && sudo mkdir -p www-data && sudo chown -R www-data:www-data www-data
sudo vim /etc/passwd
```
www-data entry should look something like this:
```
www-data:x:33:33:www-data:/home/www-data:/bin/bash
```
NB! Do not use /var/www as home directory since this might expose your private key to the world!

Login as www-data and generate your private/public keys:
```
sudo su - www-data
chmod 700 ~/.ssh
ssh-keygen -t rsa -b 4096
```
Open your repository on bitbucket.org and go to `Settings` -> `Access keys` and click on `Add key` and use the contents of the `~/.ssh/id_rsa.pub` as key:
```
ssh-rsa ... www-data@example.com
```

This will allow the user running the webserver (Trac+BitbucketSyncPlugin) to fetch updates for your repos from Bitbucket whenever the webhook is triggered.

### Clone your repository locally

In this example I will use `/var/lib/git` as base directory, I assume you already have `git` installed:

```
cd /var/lib/ && sudo mkdir git && sudo chown www-data git
sudo su - www-data
cd /var/lib/git
git clone git@bitbucket.org:<team/user>/<repository>.git
```

### Setup post-receive hook for your local git repository

* https://trac.edgewall.org/wiki/TracGit
* https://trac.edgewall.org/wiki/TracRepositoryAdmin#Git
* https://trac.edgewall.org/ticket/10730#comment:11

### Add your repository to Trac

Open your Trac installation and go to `Admin` -> `Repositories` to add the git repo you just cloned:
```
Name: <repository>
Type: git
Directory: /var/lib/git/<repository>
```
Optionally resync as Trac instructs you to.

## TracTicketChangesets plugin

If you use the TracTicketChangesets plugin, you need to switch to the branch `t7301-mercurial` instead of `trunk`
See https://trac-hacks.org/ticket/7301 for more info about the issue with Git/Mercurial and string revisions.

```
easy_install -Z https://trac-hacks.org/svn/tracticketchangesetsplugin/t7301-mercurial/
cd /usr/local/lib/python2.7/dist-packages/TracTicketChangesets-1.0dev_r0-py2.7.egg
wget https://trac-hacks.org/raw-attachment/ticket/7301/fix-t7301-youngest-rev-handling.diff
patch -p0 < fix-t7301-youngest-rev-handling.diff
wget https://trac-hacks.org/raw-attachment/ticket/7301/fix-t7301-changeset-ticket-displaying.diff
patch -p0 < fix-t7301-changeset-ticket-displaying.diff
# Manually apply 2nd hunk for web_ui.py which fails
```
Note. paths to the Trac Python plugins may differ depending on your installation.

Edit trac.ini for your environment and add
```
[ticket-changesets]
showrevlog = false
compact = false
```
Compacting revisions works for numbers, not so much for strings.
Revision logs only lists the numeric revisions, so it is no longer complete.

## Debugging

If it still does not work, you can try the following steps:

* Open your repository on bitbucket.org and go to `Settings` -> `Webhooks` and click on `View requests` for your Trac webhook.
  The status should be 200/green, if not, try to look for any clues in the details.
* `tail -f /var/lib/trac/<trac-env>/log/trac.log` for your Trac environment while committing to your repository, optionally with `log_level = DEBUG` in `/var/lib/trac/<trac-env>/conf/trac.ini`.