.PHONY: lint build build-waves run-mock run-mock-waves build-pacman run-pacman build-template run-template build-basicassets run-basicassets doctor profile-build profile-run test test-matrix clean
lint build build-waves run-mock run-mock-waves build-pacman run-pacman build-template run-template build-basicassets run-basicassets doctor profile-build profile-run test test-matrix clean:
	$(MAKE) -C apfsim $@
