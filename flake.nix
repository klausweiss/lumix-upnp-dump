{
  description = "A program to dump media from Lumix cameras on the network";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable-small";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    pyproject-nix,
    uv2nix,
    pyproject-build-systems,
    ...
  }:
    let
      inherit (nixpkgs) lib;

      workspace = uv2nix.lib.workspace.loadWorkspace {workspaceRoot = ./.;};

      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      };

      editableOverlay = workspace.mkEditablePyprojectOverlay {
        root = "$REPO_ROOT";
      };

      pythonSets = lib.genAttrs lib.systems.flakeExposed (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python312;
        in
        (pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        }).overrideScope (
          lib.composeManyExtensions [
            pyproject-build-systems.overlays.default
            overlay
          ]
        )
      );
    in
      flake-utils.lib.eachDefaultSystem (system: let
        pkgs = nixpkgs.legacyPackages.${system};
        pythonSet = pythonSets.${system};
      in {
        packages = {
          lumix-upnp-dump = pythonSet.mkVirtualEnv "lumix-upnp-dump-env" workspace.deps.default;
          default = self.packages.${system}.lumix-upnp-dump;
        };

      # Shell for app dependencies.
      #
      #     nix develop
      #
      # Use this shell for developing your app.
      devShells.default = let
        editablePythonSet = pythonSet.overrideScope editableOverlay;
        virtualenv = editablePythonSet.mkVirtualEnv "lumix-upnp-dump-dev-env" workspace.deps.all;
      in
        pkgs.mkShell {
          packages = [
            virtualenv
            pkgs.uv
          ];
          env = {
            UV_NO_SYNC = "1";
            UV_PYTHON = editablePythonSet.python.interpreter;
            UV_PYTHON_DOWNLOADS = "never";
          };
          shellHook = ''
            unset PYTHONPATH
            export REPO_ROOT=$(git rev-parse --show-toplevel)
          '';
        };

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
            users.groups.lumix-upnp-dump = {};
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
              wantedBy = ["multi-user.target"];
              requires = ["network.target"];
              path = with pkgs; [bash];
              serviceConfig = let
                pkg = self.packages.${system}.default;
              in {
                ExecStart = "${pkg}/bin/lumix-upnp-dump --config-file /etc/lumix-upnp-dump/lumix-upnp-dump.toml";
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
