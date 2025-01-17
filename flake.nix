{
  description = "A program to dump media from Lumix cameras on the network";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable-small";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix, }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        # see https://github.com/nix-community/poetry2nix/tree/master#api for more functions and examples.
        pkgs = nixpkgs.legacyPackages.${system};
        inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; })
          mkPoetryApplication;
        p2n = import poetry2nix { inherit pkgs; };
      in {
        packages = {
          lumix-upnp-dump = mkPoetryApplication {
            projectDir = self;
            overrides = p2n.defaultPoetryOverrides.extend (final: prev: {
              upnpclient = prev.upnpclient.overridePythonAttrs (old: {
                buildInputs = (old.buildInputs or [ ])
                  ++ [ pkgs.poetry pkgs.python312Packages.poetry-core ];
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
          inputsFrom = [ self.packages.${system}.lumix-upnp-dump ];
        };

        # Shell for poetry.
        #
        #     nix develop .#poetry
        #
        # Use this shell for changes to pyproject.toml and poetry.lock.
        devShells.poetry = pkgs.mkShell { packages = [ pkgs.poetry ]; };

        nixosModules.lumix-upnp-dump = { config, pkgs, lib, ... }:
          with lib;
          let cfg = config.services.lumix-upnp-dump;
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
              commandAfterFinish = mkOption {
                type = types.str;
                description = ''
                  Command to run after dumping media from a camera is completed.
                '';
                default = "";
              };
            };
            config = mkIf cfg.enable {
              # allow upnp discovery from the device
              # ref https://github.com/NixOS/nixpkgs/issues/161328
              networking.firewall.extraPackages = [ pkgs.ipset ];
              networking.firewall.extraCommands = ''
                if ! ipset --quiet list upnp; then
                  ipset create upnp hash:ip,port timeout 3
                fi
                iptables -A OUTPUT -d 239.255.255.250/32 -p udp -m udp --dport 1900 -j SET --add-set upnp src,src --exist
                iptables -A nixos-fw -p udp -m set --match-set upnp dst,dst -j nixos-fw-accept
              '';
              users.groups.lumix-upnp-dump = { };
              users.users.lumix-upnp-dump = {
                isSystemUser = true;
                group = "lumix-upnp-dump";
              };
              environment.etc."lumix-upnp-dump/lumix-upnp-dump.toml" = {
                user = "lumix-upnp-dump";
                group = "lumix-upnp-dump";
                text = ''
                  [lumix-upnp-dump]
                  output-dir = "${toString (cfg.outputFolder)}"
                  command-after-finish = ''''
                    ${cfg.commandAfterFinish}
                    ''''
                '';
              };
              systemd.services.lumix-upnp-dump = {
                enable = true;
                wantedBy = [ "multi-user.target" ];
                requires = [ "network.target" ];
                path = with pkgs; [ bash ];
                serviceConfig = let pkg = self.packages.${system}.default;
                in {
                  ExecStart =
                    "${pkg}/bin/lumix-upnp-dump --config-file /etc/lumix-upnp-dump/lumix-upnp-dump.toml";
                  Type = "simple";
                  User = "lumix-upnp-dump";
                  Group = "lumix-upnp-dump";
                  ReadWritePaths = toString (cfg.outputFolder);

                  # ref https://gist.github.com/ageis/f5595e59b1cddb1513d1b425a323db04
                  PrivateTmp = "yes";
                  NoNewPrivileges = "yes";
                  PrivateDevices = "yes";
                  DevicePolicy = "closed";
                  ProtectSystem = "strict";
                  ProtectHome = "read-only";
                  ProtectControlGroups = "yes";
                  ProtectKernelModules = "yes";
                  ProtectKernelTunables = "yes";
                  RestrictAddressFamilies =
                    "AF_UNIX AF_INET AF_INET6 AF_NETLINK";
                  RestrictNamespaces = "yes";
                  RestrictRealtime = "yes";
                  RestrictSUIDSGID = "yes";
                  MemoryDenyWriteExecute = "yes";
                  LockPersonality = "yes";
                };
              };
            };
          };
      }) // {
        formatter.x86_64-linux = nixpkgs.legacyPackages.x86_64-linux.alejandra;
      };
}
