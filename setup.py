from setuptools import setup

VERSION = '0.2'
PACKAGE = 'bitbucketsync'

setup(name = 'BitbucketSyncPlugin',
      version = VERSION,
      description = "Sync Bitbucket repository with local repository used by Trac.",
      author = 'Mitar',
      author_email = 'mitar.trac@tnode.com',
      maintainer = 'Lele Gaifax',
      maintainer_email = 'lele@metapensiero.it',
      url = 'http://mitar.tnode.com/',
      keywords = 'trac plugin',
      license = "AGPLv3",
      packages = [PACKAGE],
      include_package_data = True,
      install_requires = [],
      zip_safe = False,
      entry_points = {
          'trac.plugins': '%s = %s' % (PACKAGE, PACKAGE),
      },
)
