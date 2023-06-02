from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in tekcom_hrms/__init__.py
from tekcom_hrms import __version__ as version

setup(
	name="tekcom_hrms",
	version=version,
	description="Personalizaciones Recursos Humanos para TEK-COM",
	author="Cuatrocubos Soluciones",
	author_email="jgiron@cuatrocubos.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
