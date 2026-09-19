.PHONY: validate test install install-echo prompt

validate:
	python3 scripts/validate.py

test:
	python3 -m unittest discover -s tests -p 'test_*.py' -v

install:
	./scripts/install.sh

install-echo:
	./echo-mode/scripts/install.sh

prompt:
	@cat references/linkedai-loop-prompt.md
