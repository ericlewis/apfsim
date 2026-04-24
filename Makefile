.PHONY: lint build build-waves run-mock run-mock-waves build-pacman run-pacman test clean
lint build build-waves run-mock run-mock-waves build-pacman run-pacman test clean:
	$(MAKE) -C apfsim $@
