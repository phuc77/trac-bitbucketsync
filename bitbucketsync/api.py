import json

from trac.core import Component, implements
from trac.web import IRequestHandler, IRequestFilter, RequestDone
from trac.versioncontrol import RepositoryManager

from functools import partial
from subprocess import Popen, PIPE
import sys

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

    def fetch(self):
        p = self.__pipe('fetch', '--verbose', 'origin', stderr=PIPE)

        stdout_data, stderr_data = p.communicate()

        seen = set()
        hashes = []

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

    def post_process_request(req, template, data, content_type):
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

        payload = json.loads(req.args.get('payload'))
        repository = payload.get('repository', {})
        name = repository.get('name')
        kind = repository.get('scm')

        if not repository:
            self.env.log.error('BitbucketSync: Invalid POST payload, no repository slug')
        elif not name:
            self.env.log.error('BitbucketSync: Invalid POST payload, no repository name')
        elif not kind:
            self.env.log.error('BitbucketSync: Invalid POST payload, no repository kind')
        else:
            self.env.log.debug('BitbucketSync: Got POST request for repository "%s" (%s)',
                               name, kind)
            self._process_repository(name, kind)

        req.send_response(200)
        req.send_header('Content-Type', 'text/plain')
        req.send_header('Content-Length', 0)
        req.end_headers()

        raise RequestDone

    def _process_repository(self, name, kind):
        rm = RepositoryManager(self.env)
        repo = rm.get_repository(name)
        if kind == 'hg':
            self._process_hg_repository(rm, repo)
        elif kind == 'git':
            self._process_git_repository(rm, repo)

    def _process_git_repository(self, manager, repo):
        path = repo.gitrepo
        git = GitCore(path) # repo.git.repo
        self.env.log.debug('BitbucketSync: Executing a fetch inside "%s"', path)
        hashes = git.fetch()
        if hashes:
            self.env.log.debug('BitbucketSync: Added %d new changesets from "%s"',
                               len(hashes), path)
            manager.notify('changeset_added', repo.reponame, hashes)

    def _process_hg_repository(self, manager, repo):
        from mercurial import commands

        path = repo.path
        hgui = repo.ui
        self.env.log.debug('BitbucketSync: Executing a pull inside "%s"', path)
        commands.pull(hgui, repo.repo)
