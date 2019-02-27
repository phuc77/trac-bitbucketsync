from functools import partial
import json
from subprocess import Popen, PIPE
import sys

from trac.core import Component, implements
from trac.web import IRequestHandler, IRequestFilter, RequestDone
from trac.versioncontrol import RepositoryManager


# This is a slightly modified version of tracopt.versioncontrol.git.PyGIT.GitCore
# that unfortunately does not return git stderr, and ``git fetch --verbose`` writes
# there. I need to execute that command because currently there isn't a hook triggered
# by a fetch inside a bare repository...

class GitCore(object):
    """Low-level wrapper around git executable"""

    def __init__(self, git_dir=None, git_bin='git'):
        self.__git_bin = git_bin
        self.__git_dir = git_dir

    def __repr__(self):
        return '<GitCore bin="%s" dir="%s">' % (self.__git_bin,
                                                self.__git_dir)

    def __build_git_cmd(self, gitcmd, *args):
        """construct command tuple for git call suitable for Popen()"""

        cmd = [self.__git_bin]
        if self.__git_dir:
            cmd.append('--git-dir')
            cmd.append('%s/.git' % self.__git_dir)
            cmd.append('--work-tree')
            cmd.append(self.__git_dir)
        cmd.append(gitcmd)
        cmd.extend(args)

        return cmd

    def __pipe(self, git_cmd, *cmd_args, **kw):
        kw['env'] = {'LANG': ''}
        if sys.platform == 'win32':
            return Popen(self.__build_git_cmd(git_cmd, *cmd_args), **kw)
        else:
            return Popen(self.__build_git_cmd(git_cmd, *cmd_args),
                         close_fds=True, **kw)

    def __execute(self, git_cmd, *cmd_args):
        """execute git command and return file-like object of stdout"""

        #print >>sys.stderr, "DEBUG:", git_cmd, cmd_args

        p = self.__pipe(git_cmd, stdout=PIPE, stderr=PIPE, *cmd_args)

        stdout_data, stderr_data = p.communicate()

        return stdout_data, stderr_data

    def __getattr__(self, name):
        if name[0] == '_' or name in ('fetch',):
            raise AttributeError, name
        return partial(self.__execute, name.replace('_','-'))

    def fetch(self, logger, remote='origin'):
        p = self.__pipe('fetch', '--verbose', remote, stderr=PIPE)

        stdout_data, stderr_data = p.communicate()

        seen = set()
        hashes = []

        try:
            lines = stderr_data.splitlines()

            # drop first line, 'From /path/to/original/repo'
            lines.pop(0)

            for line in lines:
                if line.startswith(' = '):
                    # up-to-date branch, ' = [up to date]      master     -> master'
                    continue
                hash_range = line.split()[0]
                if not '..' in hash_range:
                    continue
                for hash in self.rev_list('--reverse', hash_range)[0].splitlines():
                    if not hash in seen:
                        seen.add(hash)
                        hashes.append(hash)
        except IndexError:
            logger.error('BitbucketSync: stderr: %s', stderr_data)
        return hashes


# See https://confluence.atlassian.com/display/BITBUCKET/Write+brokers+%28hooks%29+for+Bitbucket

class BitbucketSync(Component):
    """This component syncs Bitbucket repository with local repository used by Trac."""

    implements(IRequestHandler, IRequestFilter)

    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        """Called after initial handler selection, and can be used to change
        the selected handler or redirect request."""

        if self.match_request(req):
            # We disable CSRF protection here and force ourselves as a handler
            req.form_token = None
            return self

        return handler

    def post_process_request(self, req, template, data, content_type):
        """Do any post-processing the request might need; typically adding
        values to the template `data` dictionary, or changing template or
        mime type."""

        return (template, data, content_type)

    # IRequestHandler methods
    def match_request(self, req):
        """Return whether the handler wants to process the given request."""

        return req.method == 'POST' and req.path_info == '/bitbucketsync'

    def process_request(self, req):
        """Process the request."""

        payload = req.args.get('payload') if len(req.args) > 0 else req.read()
        if payload is None:
            self.env.log.error('BitbucketSync: Invalid POST, no payload')
        else:
            try:
                payload = json.loads(payload)
            except:
                self.env.log.error('BitbucketSync: Invalid POST payload')
            else:
                # Bitbucket - https://confluence.atlassian.com/bitbucket/event-payloads-740262817.html#EventPayloads-Push
                repository = payload.get('repository', {})
                # Gitlab - https://docs.gitlab.com/ee/user/project/integrations/webhooks#push-events
                project = payload.get('project', {})

                if 'name' in repository:
                    name = repository.get('name')
                elif 'name' in project:
                    name = project.get('name')

                # Defaults to git if we cant find scm property
                kind = repository.get('scm', 'git')

                if 'full_name' in repository:
                    # Build git_url and https_url for Bitbucket using full_name: "user/reponame"
                    full_name = repository.get('full_name')
                    git_url = 'git@bitbucket.org:' + full_name + '.git'
                    https_url = 'https://bitbucket.org/' + full_name + '.git'
                elif 'absolute_url' in repository:
                    # Legacy support for absolute_url: "/user/reponame/"
                    absolute_url = repository.get('absolute_url')
                    if absolute_url.startswith('/'):
                        absolute_url = absolute_url[1:]
                    if absolute_url.endswith('/'):
                        absolute_url = absolute_url[:-1]
                    git_url = 'git@bitbucket.org:' + absolute_url + '.git'
                    https_url = 'https://bitbucket.org/' + absolute_url + '.git'
                    

                if 'git_ssh_url' in project:
                    # Get git_url for Gitlab
                    git_url = project.get('git_ssh_url')
                elif 'git_ssh_url' in repository:
                    # Get git_url for Gitlab, legacy support
                    git_url = repository.get('git_ssh_url')

                if 'git_http_url' in project:
                    # Get https_url for Gitlab
                    https_url = project.get('git_http_url')
                elif 'git_http_url' in repository:
                    # Get https_url for Gitlab, legacy support
                    https_url = repository.get('git_http_url')

                if not name:
                    self.env.log.error(
                        'BitbucketSync: Invalid POST payload, no repository/project name')
                elif not git_url:
                    self.env.log.error(
                        'BitbucketSync: Invalid POST payload, no repository/project git url')
                elif not https_url:
                    self.env.log.error(
                        'BitbucketSync: Invalid POST payload, no repository/project https url')
                else:
                    self.env.log.debug(
                        'BitbucketSync: Got POST request from %s repository "%s" with url "%s"', 
                        kind, name, git_url)
                    self._process_repository(name, kind, git_url, https_url)

        req.send_response(200)
        req.send_header('Content-Type', 'text/plain')
        req.send_header('Content-Length', 0)
        req.end_headers()

        raise RequestDone

    def _process_repository(self, name, kind, git_url, https_url):
        rm = RepositoryManager(self.env)
        repo, remote = self._find_repository(rm, name, kind, git_url, https_url)
        if repo is None:
            self.env.log.warn('BitbucketSync: Cannot find a %s repository named "%s"'
                              ' with git url "%s" or https url "%s"' % (kind, name, git_url, https_url))
        elif kind == 'hg':
            self._process_hg_repository(rm, repo, remote)
        elif kind == 'git':
            self._process_git_repository(rm, repo, remote)

    def _find_repository(self, manager, name, kind, git_url, https_url):
        if kind == 'hg':
            check_urls = self._find_hg_remote
        elif kind == 'git':
            check_urls = self._find_git_remote

        for repo in manager.get_real_repositories():
            remote = check_urls(repo, git_url, https_url)
            if remote is not None:
                return repo, remote

        return None, None

    def _find_hg_remote(self, repo, git_url, https_url):
        # Should use "hg paths" to find the right remote
        raise NotImplementedError()

    def _find_git_remote(self, repo, git_url, https_url):
        try:
            git = repo.git.repo
            for remote in git.remote('--verbose').splitlines():
                name, url = remote.split('\t')
                url = url.split()[0]
                if (url == git_url or url == https_url or url.startswith('https://') and url.endswith(https_url[8:])):
                    return name
        except AttributeError:
            # Safeguard against SVN repos which does not have git property
            self.env.log.debug('BitbucketSync: Skipping "%s" since it is not a git repo', repo.name)
        return None

    def _process_git_repository(self, manager, repo, remote):
        path = repo.gitrepo
        git = GitCore(path) # repo.git.repo
        self.env.log.debug('BitbucketSync: Executing a fetch from "%s" inside "%s"',
                           remote, path)
        hashes = git.fetch(self.env.log, remote)
        if hashes:
            manager.notify('changeset_added', repo.reponame, hashes)
            self.env.log.info('BitbucketSync: Added %d new changeset(s) to "%s"', len(hashes), repo.reponame)
        else:
            self.env.log.info('BitbucketSync: No new changesets for "%s"', repo.reponame)

    def _process_hg_repository(self, manager, repo, remote):
        from mercurial import commands

        path = repo.path
        hgui = repo.ui
        self.env.log.debug('BitbucketSync: Executing a pull inside "%s"', path)
        commands.pull(hgui, repo.repo)
