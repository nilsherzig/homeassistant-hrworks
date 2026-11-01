{
  description = "HR WORKS employee CLI and Python library (browser-daemon), and the Home Assistant integration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    browser-daemon = {
      url = "github:pschmitt/browser-daemon";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      browser-daemon,
    }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
      ];
    in
    {
      packages = forAllSystems (
        system:
        let
          hrworks = nixpkgs.legacyPackages.${system}.callPackage ./nix/package.nix {
            inherit (browser-daemon.packages.${system}) browser-daemon-client;
          };
        in
        {
          inherit hrworks;
          default = hrworks;
        }
      );
      apps = forAllSystems (system: {
        default = self.apps.${system}.hrworks;
        hrworks = {
          type = "app";
          program = "${self.packages.${system}.hrworks}/bin/hrworks";
        };
      });
      nixosModules = {
        default = self.nixosModules.cli;
        cli = import ./nix/cli-module.nix self;
      };
      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python3.withPackages (ps: [
            ps.aiohttp
            ps.rich
            ps.typer
            browser-daemon.packages.${system}.browser-daemon-client
            # Installed distribution metadata for the CLI version lookup; the
            # sources on PYTHONPATH (see shellHook) take precedence.
            (ps.toPythonModule self.packages.${system}.hrworks)
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.just
              pkgs.nixfmt
              pkgs.nodejs
              pkgs.ruff
            ];
            # The tests import the repo root (custom_components) and hrworks from
            # the component directory, as the wheel layout does. Link only the
            # hrworks package: putting custom_components/hrworks itself on the
            # path would let its calendar.py shadow the standard library.
            shellHook = ''
              dev_path="''${TMPDIR:-/tmp}/hrworks-dev-pythonpath-$(id -u)"
              mkdir -p "$dev_path"
              ln -sfn "$PWD/custom_components/hrworks/hrworks" "$dev_path/hrworks"
              export PYTHONPATH="$PWD:$dev_path''${PYTHONPATH:+:$PYTHONPATH}"
            '';
          };
        }
      );
      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);
    };
}
