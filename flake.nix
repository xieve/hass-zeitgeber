{
  description = "Flake using pyproject.toml metadata";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
  inputs.pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";

  outputs =
    { nixpkgs, pyproject-nix, ... }:
    let
      inherit (nixpkgs) lib;
      forAllSystems = lib.genAttrs lib.systems.flakeExposed;

      project = pyproject-nix.lib.project.loadPyproject {
        projectRoot = ./.;
      };

      pythonAttr = "python3";
    in
    {
      devShells = forAllSystems (system: {
        default =
          let
            pkgs = nixpkgs.legacyPackages.${system};
            python = pkgs.${pythonAttr}.override {
              packageOverrides = self: super: {
                homeassistant = super.toPythonModule pkgs.home-assistant;
              };
            };
            pythonEnv = python.withPackages (
              project.renderers.withPackages {
                inherit python;
                groups = [ "dev" ];
              }
            );
          in
          pkgs.mkShell { packages = [ pythonEnv ]; };
      });

      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.${pythonAttr};
          domain = "zeitgeber";
        in
        {
          default = pkgs.buildHomeAssistantComponent (
            project.renderers.buildPythonPackage { inherit python; }
            // {
              inherit domain;
              version = (lib.importJSON "${./.}/custom_components/${domain}/manifest.json").version;
              owner = "claytonjn";
              pyproject = true;
            }
          );
        }
      );
    };
}
