import { render, screen } from "@testing-library/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Providers } from "./providers";

function QueryClientProbe() {
  const client = useQueryClient();
  return <p>{client ? "client present" : "client missing"}</p>;
}

function QueryProbe() {
  const { data, isPending } = useQuery({
    queryKey: ["probe"],
    queryFn: async () => "loaded",
  });
  return <p>{isPending ? "loading" : data}</p>;
}

describe("Providers (client boundary)", () => {
  it("exposes a QueryClient to its children", () => {
    render(
      <Providers>
        <QueryClientProbe />
      </Providers>,
    );
    expect(screen.getByText("client present")).toBeInTheDocument();
  });

  it("lets children resolve a query through that client", async () => {
    render(
      <Providers>
        <QueryProbe />
      </Providers>,
    );
    expect(await screen.findByText("loaded")).toBeInTheDocument();
  });

  it("throws without the provider, proving the boundary is real", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<QueryClientProbe />)).toThrow(/No QueryClient set/);
    vi.restoreAllMocks();
  });
});
