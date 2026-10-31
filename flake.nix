{
  description = "HR WORKS for Home Assistant (development shell)";

  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
      ];
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python3.withPackages (ps: [ ps.aiohttp ]);
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
            # The tests import hrworks from the component directory. Link only the
            # hrworks package: putting custom_components/hrworks itself on the path
            # would let its calendar.py shadow the standard library. Put the checkout
            # of browser-daemon's python/ directory (browser-daemon-client) in
            # BROWSER_DAEMON_CLIENT_PATH.
            shellHook = ''
              dev_path="''${TMPDIR:-/tmp}/hrworks-dev-pythonpath-$(id -u)"
              mkdir -p "$dev_path"
              ln -sfn "$PWD/custom_components/hrworks/hrworks" "$dev_path/hrworks"
              export PYTHONPATH="$PWD:$dev_path''${BROWSER_DAEMON_CLIENT_PATH:+:$BROWSER_DAEMON_CLIENT_PATH}''${PYTHONPATH:+:$PYTHONPATH}"
            '';
          };
        }
      );
      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);
    };
}
