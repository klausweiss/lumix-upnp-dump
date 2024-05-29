{
  description = "Application packaged using poetry2nix";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable-small";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        # see https://github.com/nix-community/poetry2nix/tree/master#api for more functions and examples.
        pkgs = nixpkgs.legacyPackages.${system};
        inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; }) mkPoetryApplication;
        p2n = import poetry2nix { inherit pkgs; };
      in
      {
        packages = {
          lumix_upnp_dump = mkPoetryApplication { 
            projectDir = self; 
            overrides = p2n.defaultPoetryOverrides.extend (final: prev: { 
              upnpclient = prev.upnpclient.overridePythonAttrs (old: {
                buildInputs = (old.buildInputs or [ ]) ++ [
                  pkgs.poetry
                  pkgs.python311Packages.poetry-core
                ];
              });

            });
          };
          default = self.packages.${system}.lumix_upnp_dump;
        };

        # Shell for app dependencies.
        #
        #     nix develop
        #
        # Use this shell for developing your app.
        devShells.default = pkgs.mkShell {
          inputsFrom = [ self.packages.${system}.lumix_upnp_dump ];
        };

        # Shell for poetry.
        #
        #     nix develop .#poetry
        #
        # Use this shell for changes to pyproject.toml and poetry.lock.
        devShells.poetry = pkgs.mkShell {
          packages = [ pkgs.poetry ];
        };
      });
}
