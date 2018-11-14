import sys

from setuptools import setup, find_packages

if not sys.version_info >= (3, 5):
    sys.exit("This tool was developed on Python 3.5, please upgrade")

setup(
    name="rebootmgr",
    version="0.0.20",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "click>=6.0",
        "colorlog>=3.1",
        "python-consul>=1.1",
        "requests>=2.20",
        "retrying>=1.3",
        "holidays>=0.9",
        # TODO(sneubauer): Pin consul_lib once it is released on pypi
        "consul_lib",
    ],
    entry_points="""
        [console_scripts]
        rebootmgr=rebootmgr.main:cli
    """,
)
