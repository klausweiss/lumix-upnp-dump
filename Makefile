lumix_upnp_dump.pex: lumix_upnp_dump.py requirements.txt
	pex -o lumix_upnp_dump.pex --python-shebang='/usr/bin/env python3' -D . $$(cat requirements.txt) -e lumix_upnp_dump

requirements.txt: Pipfile
	 pipenv lock -r | sed "0,/pypi.org\/simple/d" | sed "s/;.*//" > requirements.txt

