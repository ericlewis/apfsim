.PHONY: lint build build-waves run-mock run-mock-waves build-template run-template build-basicassets run-basicassets doctor profile-build profile-run profile-play test test-matrix clean

lint build build-waves run-mock run-mock-waves build-template run-template build-basicassets run-basicassets doctor profile-build profile-run profile-play test test-matrix clean:
	$(MAKE) -C apfsim $@
