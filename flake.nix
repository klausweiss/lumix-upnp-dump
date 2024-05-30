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

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    poetry2nix,
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      # see https://github.com/nix-community/poetry2nix/tree/master#api for more functions and examples.
      pkgs = nixpkgs.legacyPackages.${system};
      inherit
        (poetry2nix.lib.mkPoetry2Nix {inherit pkgs;})
        mkPoetryApplication
        ;
      p2n = import poetry2nix {inherit pkgs;};
    in {
      packages = {
        lumix-upnp-dump = mkPoetryApplication {
          projectDir = self;
          overrides = p2n.defaultPoetryOverrides.extend (final: prev: {
            upnpclient = prev.upnpclient.overridePythonAttrs (old: {
              buildInputs =
                (old.buildInputs or [])
                ++ [pkgs.poetry pkgs.python311Packages.poetry-core];
            });
          });
        };
        default = self.packages.${system}.lumix-upnp-dump;
      };

      # Shell for app dependencies.
      #
      #     nix develop
      #
      # Use this shell for developing your app.
      devShells.default = pkgs.mkShell {
        inputsFrom = [self.packages.${system}.lumix-upnp-dump];
      };

      # Shell for poetry.
      #
      #     nix develop .#poetry
      #
      # Use this shell for changes to pyproject.toml and poetry.lock.
      devShells.poetry = pkgs.mkShell {packages = [pkgs.poetry];};

      nixosModules.lumix-upnp-dump = {
        config,
        pkgs,
        lib,
        ...
      }:
        with lib; let
          cfg = config.services.lumix-upnp-dump;
        in {
          options.services.lumix-upnp-dump = {
            enable = mkOption {
              type = types.bool;
              default = false;
              description = ''
                Enable support for lumix-upnp-dump.
              '';
            };
            outputFolder = mkOption {
              type = types.path;
              description = ''
                Where to dump the media files.
              '';
            };
          };
          config = mkIf cfg.enable {
            systemd.services.lumix-upnp-dump = {
              enable = true;
              wantedBy = ["multi-user.target"];
              requires = ["network.target"];
              serviceConfig = let
                pkg = self.packages.${system}.default;
              in {
                ExecStart = "${pkg}/bin/lumix-upnp-dump -o ${
                  toString (cfg.outputFolder)
                }";
                Type = "simple";
                ReadWritePaths = cfg.outputFolder;

                PrivateTmp = "yes";
                NoNewPrivileges = "yes";
                PrivateDevices = "yes";
                DevicePolicy = "closed";
                ProtectSystem = "strict";
                ProtectHome = "read-only";
                ProtectControlGroups = "yes";
                ProtectKernelModules = "yes";
                ProtectKernelTunables = "yes";
                RestrictAddressFamilies = "AF_UNIX AF_INET AF_INET6 AF_NETLINK";
                RestrictNamespaces = "yes";
                RestrictRealtime = "yes";
                RestrictSUIDSGID = "yes";
                MemoryDenyWriteExecute = "yes";
                LockPersonality = "yes";
              };
            };
          };
        };
    })
    // {
      formatter.x86_64-linux = nixpkgs.legacyPackages.x86_64-linux.alejandra;
    };
}
